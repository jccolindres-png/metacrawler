"""Acquisition of explicitly identified Costa Rican laws, isolated from Discovery."""

import csv
import fcntl
import hashlib
import io
import json
import os
import re
import sqlite3
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from config.runtime import validate_data_root
from core.source_sidecar import write_sidecar


FIELDS = ("target_id", "jurisdiccion", "rama", "prioridad", "numero_ley",
          "titulo_buscado", "portal_oficial", "url_referencia_oficial")
STATUSES = ("pendiente", "resuelto", "descargado", "omitido", "fallido", "requiere revisión")
OFFICIAL_HOSTS = frozenset({"sinalevi.go.cr", "www.sinalevi.go.cr", "pgrweb.go.cr",
                            "www.pgrweb.go.cr", "pgr.go.cr", "www.pgr.go.cr",
                            "asamblea.go.cr", "www.asamblea.go.cr",
                            "consultassil3.asamblea.go.cr", "imprentanacional.go.cr",
                            "www.imprentanacional.go.cr"})
MAX_BYTES = 30 * 1024 * 1024
SCHEMA = """
CREATE TABLE IF NOT EXISTS targets (
 target_id TEXT PRIMARY KEY, identity_key TEXT NOT NULL, payload TEXT NOT NULL,
 status TEXT NOT NULL, source_url TEXT, final_url TEXT, acquired_at TEXT,
 version TEXT, content_hash TEXT, file_path TEXT, reason TEXT,
 imported_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS targets_identity ON targets(identity_key);
CREATE INDEX IF NOT EXISTS targets_hash ON targets(content_hash);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, target_id TEXT NOT NULL, timestamp TEXT NOT NULL,
 status TEXT NOT NULL, reason TEXT, source_url TEXT, final_url TEXT,
 version TEXT, content_hash TEXT, FOREIGN KEY(target_id) REFERENCES targets(target_id)
);
CREATE INDEX IF NOT EXISTS events_target ON events(target_id, id);
"""


def now():
    return datetime.now(timezone.utc).isoformat()


def normalized(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-zA-Z0-9]+", " ", value).lower()).strip()


def law_number(value):
    result = re.sub(r"\D", "", str(value or ""))
    return result.lstrip("0") or result


def identity(target):
    number = law_number(target.get("numero_ley"))
    title = normalized(target.get("titulo_buscado"))
    if not number and not title:
        return f"CR:sin-identidad:{target['target_id']}"
    return f"CR:ley:{number}" if number else f"CR:titulo:{title}"


def official_url(url):
    if not isinstance(url, str):
        return False
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and parsed.hostname in OFFICIAL_HOSTS
                and parsed.port in (None, 443) and not parsed.username and not parsed.password)
    except ValueError:
        return False


def _read_manifest(path):
    path = Path(path)
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("objetivos"), list):
            raise ValueError("JSON requiere un objeto raíz con lista 'objetivos'")
        return data["objetivos"]
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    raise ValueError("manifiesto debe ser .json o .csv")


def _validate_target(raw):
    if not isinstance(raw, dict):
        raise ValueError("objetivo debe ser un objeto")
    target = {field: raw.get(field) for field in FIELDS}
    for field in FIELDS:
        if target[field] == "":
            target[field] = None
    if isinstance(target["target_id"], int) and not isinstance(target["target_id"], bool):
        target["target_id"] = str(target["target_id"])
    if not isinstance(target["target_id"], str) or not re.fullmatch(r"[\w.-]{1,120}", target["target_id"]):
        raise ValueError("target_id inválido")
    if target["jurisdiccion"] != "CR":
        raise ValueError(f"{target['target_id']}: jurisdiccion debe ser CR")
    for field in FIELDS:
        if target[field] is not None and not isinstance(target[field], str):
            if ((field == "numero_ley" and isinstance(target[field], int) and not isinstance(target[field], bool))
                    or (field == "prioridad" and isinstance(target[field], (int, float))
                        and not isinstance(target[field], bool))):
                target[field] = str(target[field])
            else:
                raise ValueError(f"{target['target_id']}: {field} debe ser texto o null")
    identity(target)
    return target


class BatchStore:
    def __init__(self, client="veredictum", country="ti"):
        if (client, country) != ("veredictum", "ti"):
            raise ValueError("Batch admite únicamente veredictum/ti por ahora")
        self.root = validate_data_root() / client / country / "_batch"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "batch.sqlite3"
        self.db = sqlite3.connect(self.db_path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    def import_manifest(self, path):
        targets = [_validate_target(raw) for raw in _read_manifest(path)]
        manifest_hash = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        ids = [target["target_id"] for target in targets]
        if len(ids) != len(set(ids)):
            raise ValueError("target_id duplicado en manifiesto")
        added = unchanged = 0
        with self.db:
            for target in targets:
                payload = json.dumps(target, ensure_ascii=False, sort_keys=True)
                old = self.db.execute("SELECT payload FROM targets WHERE target_id=?", (target["target_id"],)).fetchone()
                if old:
                    if old["payload"] != payload:
                        raise ValueError(f"{target['target_id']}: importación conflictiva; estado conservado")
                    unchanged += 1
                    continue
                url = target["url_referencia_oficial"]
                status = ("requiere revisión" if not (target["numero_ley"] or target["titulo_buscado"]) else
                          "resuelto" if official_url(url) else
                          "requiere revisión" if url else "pendiente")
                stamp = now()
                self.db.execute("""INSERT INTO targets
                  (target_id, identity_key, payload, status, source_url, imported_at, updated_at)
                  VALUES (?, ?, ?, ?, ?, ?, ?)""",
                  (target["target_id"], identity(target), payload, status,
                   url, stamp, stamp))
                self.db.execute("""INSERT INTO events
                  (target_id, timestamp, status, reason, source_url)
                  VALUES (?, ?, ?, ?, ?)""",
                  (target["target_id"], stamp, status, "manifest sha256:" + manifest_hash, url))
                added += 1
        return {"total": len(targets), "importados": added, "existentes": unchanged,
                "estado": str(self.db_path)}

    def list_targets(self):
        return [dict(row) for row in self.db.execute("SELECT * FROM targets ORDER BY target_id")]

    def history(self, target_id):
        if not self.db.execute("SELECT 1 FROM targets WHERE target_id=?", (target_id,)).fetchone():
            raise ValueError("target_id desconocido")
        return [dict(row) for row in self.db.execute(
            "SELECT * FROM events WHERE target_id=? ORDER BY id", (target_id,))]

    def simulate(self):
        rows = self.list_targets()
        return {"total": len(rows), "conteo": {status: sum(r["status"] == status for r in rows)
                                           for status in STATUSES},
                "objetivos": [{"target_id": r["target_id"], "estado": r["status"],
                               "url": r["source_url"], "accion": (
                                   "sin acción" if r["status"] in ("descargado", "omitido") else
                                   "requiere identidad de norma" if not (
                                       json.loads(r["payload"]).get("numero_ley") or
                                       json.loads(r["payload"]).get("titulo_buscado")) else
                                   "requiere URL oficial" if not r["source_url"] else
                                   "URL fuera de fuentes oficiales permitidas" if not official_url(r["source_url"]) else
                                   "verificar identidad y descargar")} for r in rows]}

    def resolve(self, target_id, url):
        if not official_url(url):
            raise ValueError("URL fuera de fuentes oficiales permitidas")
        with self.db:
            row = self.db.execute("SELECT status FROM targets WHERE target_id=?", (target_id,)).fetchone()
            if row is None:
                raise ValueError("target_id desconocido")
            if row["status"] in ("descargado", "omitido"):
                raise ValueError("objetivo ya terminado")
            payload = json.loads(self.db.execute("SELECT payload FROM targets WHERE target_id=?", (target_id,)).fetchone()["payload"])
            status = "resuelto" if payload.get("numero_ley") or payload.get("titulo_buscado") else "requiere revisión"
            stamp = now()
            self.db.execute("UPDATE targets SET source_url=?, final_url=NULL, status=?, reason=NULL, updated_at=? WHERE target_id=?",
                            (url, status, stamp, target_id))
            self.db.execute("INSERT INTO events (target_id, timestamp, status, source_url) VALUES (?, ?, ?, ?)",
                            (target_id, stamp, status, url))
        return status

    def identify(self, target_id, number=None, title=None):
        if not number and not title:
            raise ValueError("se requiere numero_ley o titulo_buscado")
        with self.db:
            row = self.db.execute("SELECT * FROM targets WHERE target_id=?", (target_id,)).fetchone()
            if row is None:
                raise ValueError("target_id desconocido")
            if row["status"] in ("descargado", "omitido"):
                raise ValueError("objetivo ya terminado")
            payload = json.loads(row["payload"])
            if number:
                payload["numero_ley"] = str(number)
            if title:
                payload["titulo_buscado"] = str(title)
            status = ("resuelto" if official_url(row["source_url"]) else
                      "requiere revisión" if row["source_url"] else "pendiente")
            stamp = now()
            self.db.execute("""UPDATE targets SET identity_key=?, payload=?, status=?, reason=NULL, updated_at=?
                WHERE target_id=?""", (identity(payload), json.dumps(payload, ensure_ascii=False, sort_keys=True),
                                      status, stamp, target_id))
            self.db.execute("""INSERT INTO events (target_id, timestamp, status, reason, source_url)
                VALUES (?, ?, ?, 'identidad revisada manualmente', ?)""",
                (target_id, stamp, status, row["source_url"]))
        return status

    def _update(self, target_id, status, reason=None, **fields):
        changes = {"status": status, "reason": reason, "updated_at": now(), **fields}
        with self.db:
            self.db.execute("UPDATE targets SET " + ", ".join(f"{key}=?" for key in changes) +
                            " WHERE target_id=?", (*changes.values(), target_id))
            row = self.db.execute("SELECT source_url, final_url, version, content_hash FROM targets WHERE target_id=?",
                                  (target_id,)).fetchone()
            self.db.execute("""INSERT INTO events
                (target_id, timestamp, status, reason, source_url, final_url, version, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (target_id, changes["updated_at"], status, reason,
                 row["source_url"], row["final_url"], row["version"], row["content_hash"]))

    def run(self, target_id=None, session=None):
        lock_path = self.root / ".run.lock"
        with lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                return self._run_locked(target_id, session)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _run_locked(self, target_id=None, session=None):
        for finished in self.db.execute("SELECT * FROM targets WHERE status='descargado'").fetchall():
            path = Path(finished["file_path"] or "")
            try:
                intact = path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == finished["content_hash"]
            except OSError:
                intact = False
            if not intact:
                self._update(finished["target_id"], "requiere revisión", "archivo registrado ausente o alterado")
        query = "SELECT * FROM targets"
        args = ()
        if target_id:
            query += " WHERE target_id=?"
            args = (target_id,)
        rows = [dict(r) for r in self.db.execute(query + " ORDER BY target_id", args)]
        if target_id and not rows:
            raise ValueError("target_id desconocido")
        results = []
        for row in rows:
            if row["status"] in ("descargado", "omitido"):
                continue
            target = json.loads(row["payload"])
            if not target.get("numero_ley") and not target.get("titulo_buscado"):
                self._update(row["target_id"], "requiere revisión", "identidad de norma pendiente")
                results.append({"target_id": row["target_id"], "estado": "requiere revisión",
                                "motivo": "identidad de norma pendiente"})
                continue
            if not row["source_url"]:
                results.append({"target_id": row["target_id"], "estado": row["status"], "motivo": "URL oficial pendiente"})
                continue
            if not official_url(row["source_url"]):
                self._update(row["target_id"], "requiere revisión", "URL fuera de fuentes oficiales permitidas")
                results.append({"target_id": row["target_id"], "estado": "requiere revisión",
                                "motivo": "URL fuera de fuentes oficiales permitidas"})
                continue
            try:
                result = self._acquire(row, session or requests.Session())
            except (requests.RequestException, OSError) as exc:
                self._update(row["target_id"], "fallido", f"{type(exc).__name__}: {exc}")
                result = {"target_id": row["target_id"], "estado": "fallido", "motivo": str(exc)}
            except ValueError as exc:
                self._update(row["target_id"], "requiere revisión", str(exc))
                result = {"target_id": row["target_id"], "estado": "requiere revisión", "motivo": str(exc)}
            results.append(result)
        return results

    def _acquire(self, row, session):
        target = json.loads(row["payload"])
        existing = self.db.execute("""SELECT target_id, file_path, payload, content_hash FROM targets
            WHERE identity_key=? AND status='descargado' LIMIT 1""", (row["identity_key"],)).fetchone()
        if existing and existing["target_id"] != row["target_id"]:
            original = json.loads(existing["payload"])
            if (normalized(original.get("titulo_buscado")) and normalized(target.get("titulo_buscado"))
                    and normalized(original["titulo_buscado"]) != normalized(target["titulo_buscado"])):
                self._update(row["target_id"], "requiere revisión", "mismo número de ley con títulos distintos")
                return {"target_id": row["target_id"], "estado": "requiere revisión"}
            self._update(row["target_id"], "omitido", f"identidad ya descargada: {existing['target_id']}",
                         file_path=existing["file_path"], content_hash=existing["content_hash"])
            return {"target_id": row["target_id"], "estado": "omitido"}

        data, final_url, content_type, version = _fetch(session, row["source_url"])
        if "text/html" in content_type and not _is_normative_html(final_url):
            links = _document_links(data, final_url)
            if len(links) == 1:
                data, final_url, content_type, version = _fetch(session, links[0])
            else:
                self._update(row["target_id"], "requiere revisión",
                             f"página de referencia con {len(links)} enlaces de documento; selección no inequívoca",
                             final_url=final_url)
                return {"target_id": row["target_id"], "estado": "requiere revisión"}
        is_pdf = data.startswith(b"%PDF-")
        if is_pdf:
            if b"%%EOF" not in data[-2048:]:
                self._update(row["target_id"], "requiere revisión", "PDF incompleto o sin marcador EOF", final_url=final_url)
                return {"target_id": row["target_id"], "estado": "requiere revisión"}
            text = _pdf_text(data)
            extension = ".pdf"
        elif "text/html" in content_type:
            soup = BeautifulSoup(data, "html.parser")
            for tag in soup(["script", "style", "nav", "footer"]):
                tag.decompose()
            text = soup.get_text(" ", strip=True)
            published_version = re.search(
                r"versi[oó]n de la norma\s*:\s*(\d+\s+de\s+\d+(?:\s+del\s+\d{2}/\d{2}/\d{4})?)",
                text, re.IGNORECASE)
            if published_version:
                version = "Versión de la Norma: " + published_version.group(1)
            if not _is_normative_html(final_url):
                self._update(row["target_id"], "requiere revisión", "página HTML no es un texto normativo verificable", final_url=final_url)
                return {"target_id": row["target_id"], "estado": "requiere revisión"}
            extension = ".html"
        else:
            self._update(row["target_id"], "requiere revisión", "tipo de documento no admitido", final_url=final_url)
            return {"target_id": row["target_id"], "estado": "requiere revisión"}

        if not _matches(target, text):
            self._update(row["target_id"], "requiere revisión", "identidad de norma no verificada en el texto", final_url=final_url)
            return {"target_id": row["target_id"], "estado": "requiere revisión"}

        digest = hashlib.sha256(data).hexdigest()
        duplicate = self.db.execute("SELECT target_id FROM targets WHERE content_hash=? AND status='descargado' LIMIT 1", (digest,)).fetchone()
        if duplicate and duplicate["target_id"] != row["target_id"]:
            self._update(row["target_id"], "requiere revisión",
                         f"hash igual a otro objetivo: {duplicate['target_id']}", final_url=final_url)
            return {"target_id": row["target_id"], "estado": "requiere revisión"}

        documents = self.root / "documents"
        documents.mkdir(exist_ok=True)
        name = hashlib.sha256(row["target_id"].encode()).hexdigest()[:20] + "-" + digest[:20] + extension
        dest = documents / name
        created = False
        if dest.exists():
            if hashlib.sha256(dest.read_bytes()).hexdigest() != digest:
                raise OSError(f"conflicto con archivo existente: {dest}")
        else:
            fd, tmp = tempfile.mkstemp(prefix=".batch-", dir=documents)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.link(tmp, dest)  # exclusive: never replace an existing corpus file
                created = True
                directory_fd = os.open(documents, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        stamp = now()
        try:
            write_sidecar(dest, data, final_url, stamp)
        except Exception:
            if created:
                dest.unlink()
            raise
        self._update(row["target_id"], "descargado", None, final_url=final_url,
                     acquired_at=stamp, version=version or "captura UTC " + stamp,
                     content_hash=digest, file_path=str(dest))
        return {"target_id": row["target_id"], "estado": "descargado", "sha256": digest,
                "archivo": str(dest), "fuente": final_url}


def _fetch(session, url):
    for _ in range(6):
        if not official_url(url):
            raise ValueError("URL o redirección fuera de fuentes oficiales permitidas")
        with session.get(url, timeout=(10, 30), stream=True, allow_redirects=False,
                         headers={"User-Agent": "MetaCrawler Batch/1.0"}) as response:
            actual_url = response.url
            if not official_url(actual_url):
                raise ValueError("respuesta fuera de fuentes oficiales permitidas")
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if not location:
                    raise ValueError("redirección sin Location")
                url = urljoin(actual_url, location)
                continue
            response.raise_for_status()
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_BYTES:
                raise ValueError("documento excede límite de tamaño")
            chunks, size = [], 0
            for chunk in response.iter_content(chunk_size=65536):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError("documento excede límite de tamaño")
                chunks.append(chunk)
            version = response.headers.get("ETag") or response.headers.get("Last-Modified")
            return b"".join(chunks), actual_url, response.headers.get("Content-Type", "").lower(), version
    raise ValueError("demasiadas redirecciones")


def _pdf_text(data):
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            return ""
        return " ".join(page.extract_text() or "" for page in reader.pages[:5])
    except Exception:
        return ""


def _document_links(data, base_url):
    soup = BeautifulSoup(data, "html.parser")
    links = []
    for anchor in soup.find_all("a", href=True):
        url = urljoin(base_url, anchor["href"])
        path = urlsplit(url).path.lower()
        if official_url(url) and (path.endswith(".pdf") or path.endswith("download.aspx")):
            links.append(url)
    return list(dict.fromkeys(links))


def _is_normative_html(url):
    parsed = urlsplit(url)
    path = parsed.path.lower()
    if "nrm_texto_completo" in path or "/norma/" in path or "/normas/" in path:
        return True
    if parsed.hostname in ("sinalevi.go.cr", "www.sinalevi.go.cr") and path == "/resultadosnormativa/informacion":
        query = parse_qs(parsed.query)
        return query.get("param3") == ["1"] and bool(query.get("param1"))
    return False


def _matches(target, text):
    content = normalized(text[:20000])
    number = law_number(target.get("numero_ley"))
    title = normalized(target.get("titulo_buscado"))
    if len(content) < 100:
        return False
    if number and not re.search(r"\b(?:ley|ley numero|ley n)\s*(?:n\s*)?" + re.escape(number) + r"\b", content[:2000]):
        return False
    if title and title not in content[:5000]:
        return False
    return bool(number or title)

"""Offline regression tests for Batch and the SINALEVI cursor."""

import csv
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "Backend")]

from core.batch import BatchStore, _fetch
from clients.veredictum.crawlers.ti import sinalevi


class Response:
    def __init__(self, data, content_type="text/html", status=200, headers=None, url=None):
        self.content = data
        self.text = data.decode("utf-8", errors="ignore")
        self.status_code = status
        self.headers = {"Content-Type": content_type, **(headers or {})}
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code))

    def iter_content(self, chunk_size=None):
        yield self.content


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        item = next(self.responses)
        if isinstance(item, Exception):
            raise item
        if item.url is None:
            item.url = url
        return item


def target(target_id="a", url="https://sinalevi.go.cr/normas/ley-123"):
    return {"target_id": target_id, "jurisdiccion": "CR", "rama": "TI",
            "prioridad": 1, "numero_ley": "123", "titulo_buscado": "Ley de Prueba",
            "portal_oficial": "SINALEVI", "url_referencia_oficial": url}


DOCUMENT = ("<html><body><h1>Ley N° 123 - Ley de Prueba</h1><article>" +
            "Texto oficial de la ley. " * 20 + "</article></body></html>").encode()


def sample_pdf():
    content = b"BT /F1 12 Tf 72 720 Td (Ley N 123 Ley de Prueba " + b"texto " * 30 + b") Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    startxref = len(pdf)
    pdf += b"xref\n0 6\n0000000000 65535 f \n"
    pdf += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    pdf += b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n" + str(startxref).encode() + b"\n%%EOF\n"
    return pdf


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = mock.patch.dict(os.environ, {"METACRAWLER_DATA_ROOT": self.temp.name})
        env.start()
        self.addCleanup(env.stop)
        self.store = BatchStore()
        self.addCleanup(self.store.close)

    def manifest(self, entries):
        path = Path(self.temp.name) / "manifest.json"
        path.write_text(json.dumps({"objetivos": entries}), encoding="utf-8")
        return path

    def test_import_simulation_idempotence_and_isolation(self):
        path = self.manifest([target(), target("b", None)])
        self.assertEqual(self.store.import_manifest(path)["importados"], 2)
        with mock.patch("requests.sessions.Session.request", side_effect=AssertionError("network")):
            report = self.store.simulate()
        self.assertEqual(report["conteo"]["resuelto"], 1)
        self.assertEqual(report["conteo"]["pendiente"], 1)
        self.assertEqual(self.store.import_manifest(path)["existentes"], 2)
        self.assertFalse((Path(self.temp.name) / "veredictum/ti/_state").exists())
        self.assertFalse((Path(self.temp.name) / "veredictum/ti/_plans").exists())
        self.assertFalse((Path(self.temp.name) / "_state/dedupe_store.json").exists())

    def test_conflicting_import_rolls_back_and_quarantines_external_url(self):
        self.store.import_manifest(self.manifest([target()]))
        altered = target(); altered["titulo_buscado"] = "Otro título"
        with self.assertRaisesRegex(ValueError, "conflictiva"):
            self.store.import_manifest(self.manifest([target("new"), altered]))
        self.assertEqual(len(self.store.list_targets()), 1)
        self.assertEqual(self.store.import_manifest(self.manifest([
            target("bad", "https://sinalevi.go.cr.evil.test/a")]))["importados"], 1)
        self.assertEqual(self.store.simulate()["conteo"]["requiere revisión"], 1)
        with mock.patch("requests.sessions.Session.request", side_effect=AssertionError("network")):
            self.assertEqual(self.store.run("bad")[0]["estado"], "requiere revisión")

    def test_run_verifies_identity_saves_once_and_deduplicates_identity(self):
        self.store.import_manifest(self.manifest([target(), target("b")]))
        session = Session([Response(DOCUMENT)])
        results = self.store.run(session=session)
        self.assertEqual([r["estado"] for r in results], ["descargado", "omitido"])
        self.assertEqual(len(session.urls), 1)
        self.assertEqual(len(list((self.store.root / "documents").glob("*.source.json"))), 1)
        sidecar = next((self.store.root / "documents").glob("*.source.json"))
        provenance = json.loads(sidecar.read_text(encoding="utf-8"))
        document = Path(str(sidecar).removesuffix(".source.json"))
        self.assertEqual(provenance["source_url"], session.urls[0])
        self.assertEqual(provenance["sha256"], hashlib.sha256(document.read_bytes()).hexdigest())
        self.assertEqual(provenance["size_bytes"], document.stat().st_size)
        self.assertEqual(self.store.run(session=Session([])), [])
        reopened = BatchStore()
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.simulate()["conteo"]["descargado"], 1)

    def test_wrong_identity_and_incomplete_pdf_never_save(self):
        self.store.import_manifest(self.manifest([target()]))
        self.assertEqual(self.store.run(session=Session([Response(b"<html>Other law</html>")]))[0]["estado"],
                         "requiere revisión")
        self.assertFalse((self.store.root / "documents").exists())
        self.assertEqual(self.store.run(session=Session([Response(b"%PDF-incomplete", "application/pdf")]))[0]["estado"],
                         "requiere revisión")
        self.assertFalse((self.store.root / "documents").exists())

    def test_network_failure_retains_target_and_resolve(self):
        import requests
        self.store.import_manifest(self.manifest([target()]))
        result = self.store.run(session=Session([requests.Timeout("timeout")]))
        self.assertEqual(result[0]["estado"], "fallido")
        self.assertEqual(self.store.run(session=Session([Response(DOCUMENT)]))[0]["estado"], "descargado")
        self.assertEqual([event["status"] for event in self.store.history("a")],
                         ["resuelto", "fallido", "descargado"])
        self.store.import_manifest(self.manifest([target("unresolved", None)]))
        self.store.resolve("unresolved", "https://sinalevi.go.cr/normas/ley-123")
        self.assertEqual(self.store.simulate()["conteo"]["resuelto"], 1)

    def test_redirect_cannot_escape_official_hosts(self):
        session = Session([Response(b"", status=302, headers={"Location": "https://evil.example/file.pdf"})])
        with self.assertRaisesRegex(ValueError, "fuentes oficiales"):
            _fetch(session, "https://sinalevi.go.cr/normas/ley-123")
        self.assertEqual(len(session.urls), 1)

    def test_batch_sidecar_uses_final_url_after_official_redirect(self):
        self.store.import_manifest(self.manifest([target(url="https://sinalevi.go.cr/normas/old")]))
        redirect = Response(b"", status=302, headers={"Location": "/normas/new.pdf"})
        pdf = Response(b"%PDF-test data %%EOF", "application/pdf")
        with mock.patch("core.batch._pdf_text", return_value="Ley N 123 Ley de Prueba " + "texto " * 30):
            result = self.store.run(session=Session([redirect, pdf]))
        self.assertEqual(result[0]["estado"], "descargado")
        sidecar = next((self.store.root / "documents").glob("*.source.json"))
        self.assertEqual(json.loads(sidecar.read_text())["source_url"],
                         "https://sinalevi.go.cr/normas/new.pdf")

    def test_official_reference_with_one_pdf_link_is_verified(self):
        record = target(url="https://www.asamblea.go.cr/consulta/ley-123")
        self.store.import_manifest(self.manifest([record]))
        page = Response(b'<html><a href="/documentos/ley-123.pdf">Descargar</a></html>')
        # The PDF parser is isolated so the test checks routing and identity without a PDF fixture.
        pdf = Response(b"%PDF-test data %%EOF", "application/pdf", headers={"ETag": '"v2"'})
        session = Session([page, pdf])
        with mock.patch("core.batch._pdf_text", return_value="Ley N 123 Ley de Prueba " + "texto " * 30):
            result = self.store.run(session=session)
        self.assertEqual(result[0]["estado"], "descargado")
        self.assertEqual(len(session.urls), 2)
        self.assertEqual(self.store.list_targets()[0]["version"], '"v2"')

    def test_multiple_pdf_links_require_review(self):
        self.store.import_manifest(self.manifest([target(url="https://www.asamblea.go.cr/consulta/ley-123")]))
        page = Response(b'<a href="/a.pdf">A</a><a href="/b.pdf">B</a>')
        self.assertEqual(self.store.run(session=Session([page]))[0]["estado"], "requiere revisión")
        self.assertFalse((self.store.root / "documents").exists())

    def test_new_sinalevi_full_text_route_only(self):
        full = "https://sinalevi.go.cr/ResultadosNormativa/Informacion?param1=123&param3=1"
        self.store.import_manifest(self.manifest([target(url=full)]))
        versioned = DOCUMENT.replace(b"Texto oficial", b"Version de la Norma: 7 de 7 del 29/01/2025 Texto oficial")
        self.assertEqual(self.store.run(session=Session([Response(versioned)]))[0]["estado"], "descargado")
        self.assertEqual(self.store.list_targets()[0]["version"], "Versión de la Norma: 7 de 7 del 29/01/2025")
        partial = "https://sinalevi.go.cr/ResultadosNormativa/Informacion?param1=123&param3=2"
        other = target("partial", partial)
        other["numero_ley"] = "456"
        self.store.import_manifest(self.manifest([other]))
        self.assertEqual(self.store.run("partial", session=Session([Response(DOCUMENT)]))[0]["estado"],
                         "requiere revisión")

    def test_real_pdf_text_extraction_and_identity(self):
        self.store.import_manifest(self.manifest([target(url="https://sinalevi.go.cr/normas/ley-123.pdf")]))
        result = self.store.run(session=Session([Response(sample_pdf(), "application/pdf")]))
        self.assertEqual(result[0]["estado"], "descargado")

    def test_csv_import(self):
        path = Path(self.temp.name) / "manifest.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=target().keys())
            writer.writeheader()
            writer.writerow(target())
        self.assertEqual(self.store.import_manifest(path)["importados"], 1)

    def test_missing_file_is_not_left_marked_downloaded(self):
        self.store.import_manifest(self.manifest([target()]))
        self.store.run(session=Session([Response(DOCUMENT)]))
        Path(self.store.list_targets()[0]["file_path"]).unlink()
        self.assertEqual(self.store.run(session=Session([Response(b"<html>wrong</html>")]))[0]["estado"],
                         "requiere revisión")
        self.assertEqual(self.store.simulate()["conteo"]["descargado"], 0)

    def test_same_number_with_different_title_requires_review(self):
        alternate = target("b")
        alternate["titulo_buscado"] = "Otra Ley"
        self.store.import_manifest(self.manifest([target(), alternate]))
        result = self.store.run(session=Session([Response(DOCUMENT)]))
        self.assertEqual([r["estado"] for r in result], ["descargado", "requiere revisión"])

    def test_identical_hash_for_different_laws_requires_review(self):
        second = target("b")
        second["numero_ley"] = "456"
        self.store.import_manifest(self.manifest([target(), second]))
        document = ("<html>Ley N 123 Ley de Prueba Ley N 456 Ley de Prueba " + "texto " * 30 + "</html>").encode()
        results = self.store.run(session=Session([Response(document), Response(document)]))
        self.assertEqual([r["estado"] for r in results], ["descargado", "requiere revisión"])
        self.assertEqual(len(list((self.store.root / "documents").glob("*.source.json"))), 1)

    def test_null_identity_is_imported_without_network_until_identified(self):
        unknown = target("unknown")
        unknown["numero_ley"] = None
        unknown["titulo_buscado"] = None
        self.store.import_manifest(self.manifest([unknown]))
        self.assertEqual(self.store.simulate()["conteo"]["requiere revisión"], 1)
        with mock.patch("requests.sessions.Session.request", side_effect=AssertionError("network")):
            self.assertEqual(self.store.run("unknown")[0]["estado"], "requiere revisión")
        self.assertEqual(self.store.identify("unknown", number=123, title="Ley de Prueba"), "resuelto")
        self.assertEqual(self.store.run("unknown", session=Session([Response(DOCUMENT)]))[0]["estado"],
                         "descargado")


if __name__ == "__main__":
    unittest.main()

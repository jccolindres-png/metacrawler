"""Acquire official SINALEVI normative PDFs through its current search and export routes."""

import json
import os
import tempfile
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from core.results import CrawlerResult
from core.source_sidecar import save_download

ROOT = "https://sinalevi.go.cr"
SEARCH_URL = ROOT + "/BusquedaSimple/_CambiarResultados"
DETAIL_URL = ROOT + "/ResultadosNormativa/Informacion"
TEXT_URL = ROOT + "/ResultadosNormativa/_CargarTextoCompleto"
PDF_URL = ROOT + "/ResultadosNormativa/_GenerarPDF"
SEARCH_TERMS = ("ley", "decreto", "reglamento", "acuerdo", "resolución")
PAGE_SIZE = 10
TIMEOUT = 25
PDF_TIMEOUT = 90
HEADERS = {"User-Agent": "MetaCrawler/1.0"}


def _read_state(path):
    try:
        raw = path.read_text(encoding="utf-8").strip()
        data = {} if raw in ("", "{}") else json.loads(raw)
    except FileNotFoundError:
        data = {}
    if not isinstance(data, dict):
        raise ValueError("SINALEVI state must be an object")
    state = {"query_index": 0, "page": 1, "item_index": 0, "seen": []}
    state.update(data)
    if (any(not isinstance(state[key], int) or state[key] < minimum
            for key, minimum in (("query_index", 0), ("page", 1), ("item_index", 0)))
            or not isinstance(state["seen"], list)):
        raise ValueError("invalid SINALEVI state")
    return state


def _save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".sinalevi-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _failed(exc, url, reason="SINALEVI request failed; cursor retained"):
    response = getattr(exc, "response", None)
    return CrawlerResult("failed", reason, "sinalevi", attempted_url=url,
                         http_status=getattr(response, "status_code", None),
                         error_type=type(exc).__name__, error_message=str(exc), retryable=True)


def _get(session, url, **kwargs):
    response = session.get(url, timeout=TIMEOUT, headers=HEADERS, **kwargs)
    if response.status_code != 200 or not response.content:
        raise requests.HTTPError(f"HTTP {response.status_code} or empty response", response=response)
    return response


def _post(session, url, timeout=TIMEOUT, **kwargs):
    response = session.post(url, timeout=timeout, headers=HEADERS, **kwargs)
    if response.status_code != 200 or not response.content:
        raise requests.HTTPError(f"HTTP {response.status_code} or empty response", response=response)
    return response


def _advance(state, count, terms):
    state["item_index"] += 1
    if state["item_index"] >= count:
        state["item_index"] = 0
        if count == PAGE_SIZE:
            state["page"] += 1
        else:
            state["page"] = 1
            state["query_index"] = (state["query_index"] + 1) % len(terms)


def _search_params(term, page):
    return {"opcionSelected": "1", "textBuscar": term, "textAnnio": "",
            "selectedBuscarEn": "F", "TipoNorma": "", "TipoPronunciamiento": "",
            "ClaseAsunto": "", "cantidadResultados": PAGE_SIZE,
            "pagina": page, "page": page, "pageSize": PAGE_SIZE}


def download_one(source):
    """Inspect one search result and publish at most one PDF with provenance."""
    directory = Path(source["download_dir"])
    state_file = Path(source["state_file"])
    directory.mkdir(parents=True, exist_ok=True)
    terms = tuple(source.get("search_terms") or SEARCH_TERMS)
    if not terms or any(not isinstance(term, str) or not term.strip() for term in terms):
        return CrawlerResult("manual_review", "invalid search terms", "sinalevi")
    try:
        state = _read_state(state_file)
        if state["query_index"] >= len(terms):
            raise ValueError("query index outside configured search terms")
    except (OSError, ValueError, TypeError) as exc:
        return CrawlerResult("manual_review", "invalid SINALEVI cursor", "sinalevi",
                             error_type=type(exc).__name__, error_message=str(exc))
    session = requests.Session()
    term = terms[state["query_index"]]
    try:
        search = _get(session, SEARCH_URL, params=_search_params(term, state["page"]))
        records = search.json()
    except (requests.RequestException, ValueError) as exc:
        return _failed(exc, SEARCH_URL, "SINALEVI search failed; cursor retained")
    if not isinstance(records, list) or len(records) > PAGE_SIZE:
        return CrawlerResult("site_changed", "unexpected SINALEVI search response", "sinalevi",
                             attempted_url=search.url, retryable=True)
    if not records or state["item_index"] >= len(records):
        if len(records) < PAGE_SIZE:
            state["query_index"] = (state["query_index"] + 1) % len(terms)
            state["page"] = 1
        else:
            state["page"] += 1
        state["item_index"] = 0
        _save_state(state_file, state)
        return CrawlerResult("no_new_documents", "SINALEVI search page exhausted", "sinalevi",
                             attempted_url=search.url)
    record = records[state["item_index"]]
    try:
        doc_id = int(record["IdFichaNorma"])
        version = int(record["IdVersionNorma"])
        if doc_id <= 0 or version <= 0:
            raise ValueError("nonpositive identity")
    except (KeyError, TypeError, ValueError) as exc:
        return CrawlerResult("site_changed", "SINALEVI result identity missing", "sinalevi",
                             attempted_url=search.url, error_message=str(exc), retryable=True)
    identity = f"{doc_id}:{version}"
    destination = directory / f"sinalevi_norma_{doc_id}_{version}.pdf"
    stage_url = DETAIL_URL
    try:
        detail = _get(session, DETAIL_URL, params={"param1": doc_id, "param2": version, "param3": 1})
        soup = BeautifulSoup(detail.text, "html.parser")
        actual_id = soup.select_one("#idFichaNorma")
        actual_version = soup.select_one("#versionNorma")
        if (not actual_id or not actual_version or actual_id.get("value") != str(doc_id)
                or actual_version.get("value") != str(version)):
            return CrawlerResult("site_changed", "SINALEVI detail identity mismatch; cursor retained",
                                 "sinalevi", attempted_url=detail.url, retryable=True)
        stage_url = TEXT_URL
        text = _post(session, TEXT_URL, data={"idFichaNorma": doc_id, "version": version, "busqueda": ""})
        payload = text.json()
        html = payload.get("html") if isinstance(payload, dict) else None
        if not isinstance(html, str) or not BeautifulSoup(html, "html.parser").find(id="contenedorTexto"):
            return CrawlerResult("site_changed", "SINALEVI full text unavailable; cursor retained",
                                 "sinalevi", attempted_url=text.url, retryable=True)
        # The portal's button posts contenidoPDF.innerHTML after loading this fragment.
        container = soup.find(id="contenidoPDF")
        view = container.find(id="divVista") if container else None
        if view is None:
            return CrawlerResult("site_changed", "SINALEVI export container missing; cursor retained",
                                 "sinalevi", attempted_url=detail.url, retryable=True)
        view.clear()
        view.append(BeautifulSoup(html, "html.parser"))
        stage_url = PDF_URL
        pdf = _post(session, PDF_URL, timeout=PDF_TIMEOUT,
                    json={"html": container.decode_contents()})
    except (requests.RequestException, ValueError) as exc:
        return _failed(exc, stage_url, "SINALEVI document/export failed; cursor retained")
    if not pdf.content.startswith(b"%PDF") or b"%%EOF" not in pdf.content[-2048:]:
        return CrawlerResult("invalid_document", "SINALEVI export was not a complete PDF; cursor retained",
                             "sinalevi", attempted_url=pdf.url, http_status=pdf.status_code, retryable=True)
    try:
        outcome = save_download(pdf.content, destination, pdf.url,
                                source_root=directory, return_outcome=True)
    except (OSError, ValueError) as exc:
        return _failed(exc, pdf.url, "SINALEVI save failed; cursor retained")
    if identity not in state["seen"]:
        state["seen"].append(identity)
    _advance(state, len(records), terms)
    _save_state(state_file, state)
    if outcome.status == "duplicate":
        return CrawlerResult("duplicate", "SINALEVI PDF content already acquired", "sinalevi",
                             attempted_url=pdf.url, downloaded_path=str(outcome.path),
                             content_hash=outcome.content_hash)
    return "downloaded"

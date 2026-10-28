#!/usr/bin/env python3

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from pathlib import Path
from core.results import CrawlerResult
from core.source_sidecar import save_download


FALLO_PATH = "/BusquedaAPI/DetalleFallo?fallo="


def _is_pdf_response(resp: requests.Response) -> bool:
    ct = (resp.headers.get("Content-Type") or "").lower()
    return (
        resp.status_code == 200
        and "application/pdf" in ct
        and resp.content[:4] == b"%PDF"
    )


def download_one(source: dict) -> str:
    """
    CRAWLER CONTRACT — OBLIGATORIO

    - Máximo 1 ID por ejecución
    - Máximo 1 PDF por ejecución
    - Sin loops largos
    - Retorno inmediato tras descarga
    - Si no descarga nada → "skipped"
    """

    base_urls = source.get("base_urls") or []
    if not base_urls:
        return "skipped"

    base_url = base_urls[0].rstrip("/")

    download_dir = Path(source["download_dir"])
    download_dir.mkdir(parents=True, exist_ok=True)

    state_file = Path(source["state_file"])
    mode = source.get("mode", "incremental")

    # estado: último fallo intentado
    try:
        raw = state_file.read_text(encoding="utf-8").strip()
        last_id = 0 if raw in ("", "{}") else int(raw)
        if last_id < 0:
            raise ValueError("negative Poder Judicial cursor")
    except FileNotFoundError:
        last_id = 0
    except (OSError, ValueError) as exc:
        return CrawlerResult("manual_review", "invalid Poder Judicial cursor", "poder_judicial",
                             error_type=type(exc).__name__, error_message=str(exc))

    # 🔒 SOLO un ID por ejecución
    current_id = last_id + 1
    url = base_url + FALLO_PATH + str(current_id)

    try:
        page = requests.get(url, timeout=15)
    except requests.RequestException as exc:
        return CrawlerResult("failed", "Poder Judicial detail request failed; cursor retained", "poder_judicial",
                             attempted_url=url, http_status=getattr(getattr(exc, "response", None), "status_code", None),
                             error_type=type(exc).__name__, error_message=str(exc), retryable=True)

    if page.status_code != 200:
        return CrawlerResult("failed", "Poder Judicial detail HTTP failure; cursor retained", "poder_judicial",
                             attempted_url=url, http_status=page.status_code,
                             error_type="HTTPError", error_message=f"HTTP {page.status_code}", retryable=True)
    if not page.text:
        return CrawlerResult("site_changed", "empty Poder Judicial detail; cursor retained", "poder_judicial",
                             attempted_url=url, http_status=page.status_code, retryable=True)

    soup = BeautifulSoup(page.text, "html.parser")

    link = soup.find(
        "a",
        href=True,
        string=lambda t: t and "PDF" in t.upper()
    )

    if not link:
        return CrawlerResult("site_changed", "Poder Judicial PDF link missing; cursor retained", "poder_judicial",
                             attempted_url=url, http_status=page.status_code, retryable=True)

    pdf_url = urljoin(url + "/", link["href"])
    filename = f"fallo_{current_id}.pdf"
    dest = download_dir / filename

    try:
        pdf = requests.get(pdf_url, timeout=20)
    except requests.RequestException as exc:
        return CrawlerResult("failed", "Poder Judicial PDF request failed; cursor retained", "poder_judicial",
                             attempted_url=pdf_url, http_status=getattr(getattr(exc, "response", None), "status_code", None),
                             error_type=type(exc).__name__, error_message=str(exc), retryable=True)

    if pdf.status_code != 200:
        return CrawlerResult("failed", "Poder Judicial PDF HTTP failure; cursor retained", "poder_judicial",
                             attempted_url=pdf_url, http_status=pdf.status_code,
                             error_type="HTTPError", error_message=f"HTTP {pdf.status_code}", retryable=True)
    if not _is_pdf_response(pdf):
        return CrawlerResult("invalid_document", "invalid Poder Judicial PDF; cursor retained", "poder_judicial",
                             attempted_url=pdf_url, http_status=pdf.status_code, retryable=True)

    try:
        outcome = save_download(pdf.content, dest, pdf.url,
                                source_root=download_dir, return_outcome=True)
    except (OSError, ValueError) as exc:
        return CrawlerResult("failed", "Poder Judicial persistence failed; cursor retained", "poder_judicial",
                             attempted_url=pdf_url, error_type=type(exc).__name__,
                             error_message=str(exc), retryable=True)
    state_file.write_text(str(current_id), encoding="utf-8")
    if outcome.status == "duplicate":
        return CrawlerResult("duplicate", "Poder Judicial PDF already present", "poder_judicial",
                             attempted_url=pdf_url, downloaded_path=str(outcome.path),
                             content_hash=outcome.content_hash)
    return "downloaded"

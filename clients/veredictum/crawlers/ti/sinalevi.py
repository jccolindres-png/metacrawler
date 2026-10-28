#!/usr/bin/env python3

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from pathlib import Path
from core.source_sidecar import save_download
from core.results import CrawlerResult


BASE_URL = (
    "https://www.pgrweb.go.cr/scij/Busqueda/Normativa/Normas/"
    "nrm_texto_completo.aspx?param1={}"
)


def safe(name: str) -> str:
    return "".join(
        c if c.isalnum() or c in "._-" else "_"
        for c in name
    )


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

    - Máximo 1 índice por ejecución
    - Máximo 1 PDF por ejecución
    - Sin loops largos
    - Retorno inmediato tras descarga
    - Si no descarga nada → "skipped"
    """

    download_dir = Path(source["download_dir"])
    download_dir.mkdir(parents=True, exist_ok=True)

    state_file = Path(source["state_file"])
    mode = source.get("mode", "incremental")

    # estado: último índice intentado
    try:
        last_n = int(state_file.read_text(encoding="utf-8").strip())
    except Exception:
        last_n = 0

    current_n = last_n + 1
    url = BASE_URL.format(current_n)

    try:
        page = requests.get(url, timeout=15)
    except Exception:
        return "failed"

    if page.status_code != 200 or not page.text:
        return "failed"

    soup = BeautifulSoup(page.text, "html.parser")

    link = soup.find(
        "a",
        href=True,
        string=lambda t: t and "PDF" in t.upper()
    )

    if not link:
        return CrawlerResult("site_changed", "SINALEVI PDF link missing; cursor retained", "sinalevi",
                             attempted_url=url, http_status=page.status_code, retryable=True)

    pdf_url = urljoin(url, link["href"])
    filename = safe(f"sinalevi_norma_{current_n}.pdf")
    dest = download_dir / filename

    try:
        pdf = requests.get(pdf_url, timeout=20)
    except Exception:
        return "failed"

    if not _is_pdf_response(pdf):
        return CrawlerResult("invalid_document", "invalid SINALEVI PDF; cursor retained", "sinalevi",
                             attempted_url=pdf_url, http_status=pdf.status_code, retryable=True)

    try:
        outcome = save_download(pdf.content, dest, pdf.url,
                                source_root=download_dir, return_outcome=True)
    except (OSError, ValueError):
        return "failed"
    state_file.write_text(str(current_n), encoding="utf-8")
    if outcome.status == "duplicate":
        return CrawlerResult("duplicate", "SINALEVI PDF content already acquired", "sinalevi",
                             attempted_url=pdf_url, downloaded_path=str(outcome.path),
                             content_hash=outcome.content_hash)
    return "downloaded"

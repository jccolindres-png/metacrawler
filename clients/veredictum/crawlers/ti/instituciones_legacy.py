#!/usr/bin/env python3

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from pathlib import Path
from core.source_sidecar import save_download
from core.results import CrawlerResult
import os


def safe(name: str) -> str:
    return "".join(
        c if c.isalnum() or c in "._-" else "_"
        for c in name
    )


def slug_from_url(url: str) -> str:
    """
    Genera un nombre de carpeta estable a partir del dominio.
    Ej: https://www.ccss.sa.cr/normativa -> ccss_sa_cr
    """
    netloc = urlparse(url).netloc.lower()
    return netloc.replace("www.", "").replace(".", "_")


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

    - Máximo 1 archivo por ejecución
    - Retorno inmediato tras 1 descarga
    - Si no descarga nada → "skipped"
    """

    base_urls = source.get("base_urls") or []
    if not base_urls:
        return "skipped"

    base_download_dir = Path(source["download_dir"])
    base_download_dir.mkdir(parents=True, exist_ok=True)

    state_file = Path(source["state_file"])
    mode = source.get("mode", "incremental")

    session = requests.Session()
    first_failure = None
    duplicate = None

    for url in base_urls:
        inst_slug = slug_from_url(url)
        inst_dir = base_download_dir / inst_slug
        inst_dir.mkdir(parents=True, exist_ok=True)

        try:
            r = session.get(url, timeout=15)
        except requests.RequestException as exc:
            first_failure = first_failure or CrawlerResult(
                "failed", "Instituciones page request failed; cursor retained", "instituciones_legacy",
                attempted_url=url, error_type=type(exc).__name__,
                error_message=str(exc), retryable=True)
            continue
        if r.status_code != 200:
            first_failure = first_failure or CrawlerResult(
                "failed", "Instituciones page HTTP failure; cursor retained", "instituciones_legacy",
                attempted_url=url, http_status=r.status_code,
                error_type="HTTPError", error_message=f"HTTP {r.status_code}", retryable=True)
            continue
        if not r.text:
            first_failure = first_failure or CrawlerResult(
                "site_changed", "empty Instituciones page; cursor retained", "instituciones_legacy",
                attempted_url=url, http_status=r.status_code, retryable=True)
            continue

        soup = BeautifulSoup(r.text, "html.parser")
        enlaces = soup.find_all("a", href=True)

        for a in enlaces:
            href = a["href"]

            if not href.lower().endswith(".pdf"):
                continue

            pdf_url = urljoin(url, href)
            filename = safe(os.path.basename(href))
            dest = inst_dir / filename

            try:
                pdf = session.get(pdf_url, timeout=20)
            except requests.RequestException as exc:
                first_failure = first_failure or CrawlerResult(
                    "failed", "Instituciones PDF request failed; cursor retained", "instituciones_legacy",
                    attempted_url=pdf_url, error_type=type(exc).__name__,
                    error_message=str(exc), retryable=True)
                continue
            if pdf.status_code != 200:
                first_failure = first_failure or CrawlerResult(
                    "failed", "Instituciones PDF HTTP failure; cursor retained", "instituciones_legacy",
                    attempted_url=pdf_url, http_status=pdf.status_code,
                    error_type="HTTPError", error_message=f"HTTP {pdf.status_code}", retryable=True)
                continue
            if not _is_pdf_response(pdf):
                first_failure = first_failure or CrawlerResult(
                    "invalid_document", "invalid Instituciones PDF; cursor retained", "instituciones_legacy",
                    attempted_url=pdf_url, http_status=pdf.status_code, retryable=True)
                continue
            try:
                outcome = save_download(pdf.content, dest, pdf.url,
                                        source_root=base_download_dir, return_outcome=True)
            except (OSError, ValueError) as exc:
                first_failure = first_failure or CrawlerResult(
                    "failed", "Instituciones persistence failed; cursor retained", "instituciones_legacy",
                    attempted_url=pdf_url, error_type=type(exc).__name__,
                    error_message=str(exc), retryable=True)
                continue
            if outcome.status == "duplicate":
                duplicate = CrawlerResult("duplicate", "PDF content already acquired", "instituciones_legacy",
                                          attempted_url=pdf_url, downloaded_path=str(outcome.path),
                                          content_hash=outcome.content_hash)
                continue
            state_file.write_text("done", encoding="utf-8")
            return "downloaded"

        # esta URL no dio PDF → pasar a la siguiente

    if first_failure:
        return first_failure
    state_file.write_text("done", encoding="utf-8")
    return duplicate or "skipped"

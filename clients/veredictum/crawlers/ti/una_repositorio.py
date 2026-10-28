#!/usr/bin/env python3

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from pathlib import Path
from core.source_sidecar import save_download
from core.results import CrawlerResult
import os


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

    - Máximo 1 archivo por ejecución
    - Retorno inmediato tras 1 descarga
    - Si no descarga nada → "skipped"
    """

    base_urls = source.get("base_urls") or []
    if not base_urls:
        return "skipped"

    download_dir = Path(source["download_dir"])
    download_dir.mkdir(parents=True, exist_ok=True)

    state_file = Path(source["state_file"])
    mode = source.get("mode", "incremental")

    session = requests.Session()
    first_failure = None

    for base_url in base_urls:
        try:
            r = session.get(base_url, timeout=15)
        except requests.RequestException as exc:
            first_failure = first_failure or CrawlerResult(
                "failed", "UNA page request failed; cursor retained", "una_repositorio",
                attempted_url=base_url, error_type=type(exc).__name__,
                error_message=str(exc), retryable=True)
            continue
        if r.status_code != 200:
            first_failure = first_failure or CrawlerResult(
                "failed", "UNA page HTTP failure; cursor retained", "una_repositorio",
                attempted_url=base_url, http_status=r.status_code,
                error_type="HTTPError", error_message=f"HTTP {r.status_code}", retryable=True)
            continue
        if not r.text:
            first_failure = first_failure or CrawlerResult(
                "site_changed", "empty UNA page; cursor retained", "una_repositorio",
                attempted_url=base_url, http_status=r.status_code, retryable=True)
            continue

        soup = BeautifulSoup(r.text, "html.parser")
        enlaces = soup.find_all("a", href=True)

        for a in enlaces:
            href = a["href"]

            if not href.lower().endswith(".pdf"):
                continue

            pdf_url = urljoin(base_url, href)
            filename = safe(os.path.basename(href))
            dest = download_dir / filename

            if dest.exists():
                continue

            try:
                pdf = session.get(pdf_url, timeout=20)
            except requests.RequestException as exc:
                first_failure = first_failure or CrawlerResult(
                    "failed", "UNA PDF request failed; cursor retained", "una_repositorio",
                    attempted_url=pdf_url, error_type=type(exc).__name__,
                    error_message=str(exc), retryable=True)
                continue
            if pdf.status_code != 200:
                first_failure = first_failure or CrawlerResult(
                    "failed", "UNA PDF HTTP failure; cursor retained", "una_repositorio",
                    attempted_url=pdf_url, http_status=pdf.status_code,
                    error_type="HTTPError", error_message=f"HTTP {pdf.status_code}", retryable=True)
                continue
            if not _is_pdf_response(pdf):
                first_failure = first_failure or CrawlerResult(
                    "invalid_document", "invalid UNA PDF; cursor retained", "una_repositorio",
                    attempted_url=pdf_url, http_status=pdf.status_code, retryable=True)
                continue
            try:
                created = save_download(pdf.content, dest, pdf.url)
            except (OSError, ValueError) as exc:
                first_failure = first_failure or CrawlerResult(
                    "failed", "UNA persistence failed; cursor retained", "una_repositorio",
                    attempted_url=pdf_url, error_type=type(exc).__name__,
                    error_message=str(exc), retryable=True)
                continue
            if not created:
                first_failure = first_failure or CrawlerResult(
                    "manual_review", "UNA destination appeared; cursor retained", "una_repositorio",
                    attempted_url=pdf_url)
                continue
            state_file.write_text("done", encoding="utf-8")
            return "downloaded"

        # esta URL no dio PDF → pasar a la siguiente

    if first_failure:
        return first_failure
    state_file.write_text("done", encoding="utf-8")
    return "skipped"

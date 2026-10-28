#!/usr/bin/env python3

import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from pathlib import Path
from datetime import date, timedelta
from core.results import CrawlerResult
from core.source_sidecar import save_download


DEFAULT_START_DATE = date(2000, 1, 1)
REQUEST_TIMEOUT = 25


def safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in name).strip("_")


def is_pdf_response(resp: requests.Response) -> bool:
    if resp is None or resp.status_code != 200:
        return False
    ct = (resp.headers.get("Content-Type") or "").lower()
    head = resp.content[:8] if resp.content else b""
    return (
        ("application/pdf" in ct)
        or ("octet-stream" in ct)
        or ("pdf" in ct)
    ) and head.startswith(b"%PDF")


def extract_pdf_links(html: str, page_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue

        if ".pdf" in href.lower():
            links.append(urljoin(page_url, href))

    seen = set()
    out = []
    for u in links:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def download_one(source: dict) -> str:
    """
    CRAWLER CONTRACT — OBLIGATORIO

    - Máximo 1 archivo por ejecución
    - Máximo 1 fecha por ejecución
    - Retorno inmediato tras 1 descarga
    - Si no descarga nada → "skipped"
    """

    base_urls = source.get("base_urls") or []
    if not base_urls:
        return "skipped"

    base_url = base_urls[0].rstrip("/")
    download_dir = Path(source["download_dir"])
    state_file = Path(source["state_file"])
    mode = source.get("mode", "incremental")

    download_dir.mkdir(parents=True, exist_ok=True)

    try:
        last = state_file.read_text(encoding="utf-8").strip()
        if last in ("", "{}"):
            current = DEFAULT_START_DATE if mode == "full" else date.today()
        else:
            current = date.fromisoformat(last) + timedelta(days=1)
    except FileNotFoundError:
        current = DEFAULT_START_DATE if mode == "full" else date.today()
    except (OSError, ValueError, OverflowError) as exc:
        return CrawlerResult("manual_review", "invalid Gaceta cursor", "gaceta",
                             error_type=type(exc).__name__, error_message=str(exc))

    # ✅ ENDPOINT REAL DE LA GACETA (BUSCADOR LEGACY)
    page_url = (
        f"{base_url}/cgi-bin/search.pl"
        f"?query=&fecha={current.isoformat()}"
    )

    session = requests.Session()

    try:
        r = session.get(
            page_url,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Metacrawler)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
    except requests.RequestException as exc:
        return CrawlerResult("failed", "Gaceta search request failed; cursor retained", "gaceta",
                             attempted_url=page_url, http_status=getattr(getattr(exc, "response", None), "status_code", None),
                             error_type=type(exc).__name__, error_message=str(exc), retryable=True)

    if r.status_code != 200:
        return CrawlerResult("failed", "Gaceta search HTTP failure; cursor retained", "gaceta",
                             attempted_url=page_url, http_status=r.status_code,
                             error_type="HTTPError", error_message=f"HTTP {r.status_code}", retryable=True)
    if not r.text:
        return CrawlerResult("site_changed", "empty Gaceta search response; cursor retained", "gaceta",
                             attempted_url=page_url, http_status=r.status_code, retryable=True)

    pdf_links = extract_pdf_links(r.text, page_url)

    duplicates = 0
    for pdf_url in pdf_links:
        name = os.path.basename(urlparse(pdf_url).path) or f"gaceta_{current.isoformat()}.pdf"
        name = safe(name if ".pdf" in name.lower() else f"{name}.pdf")
        filename = safe(f"gaceta_{current.isoformat()}_{name}")
        dest = download_dir / filename

        try:
            pdf = session.get(
                pdf_url,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Metacrawler)",
                    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
                    "Referer": page_url,
                },
            )
        except requests.RequestException as exc:
            return CrawlerResult("failed", "Gaceta PDF request failed; cursor retained", "gaceta",
                                 attempted_url=pdf_url, http_status=getattr(getattr(exc, "response", None), "status_code", None),
                                 error_type=type(exc).__name__, error_message=str(exc), retryable=True)

        if pdf.status_code != 200:
            return CrawlerResult("failed", "Gaceta PDF HTTP failure; cursor retained", "gaceta",
                                 attempted_url=pdf_url, http_status=pdf.status_code,
                                 error_type="HTTPError", error_message=f"HTTP {pdf.status_code}", retryable=True)
        if not is_pdf_response(pdf):
            return CrawlerResult("invalid_document", "invalid Gaceta PDF; cursor retained", "gaceta",
                                 attempted_url=pdf_url, http_status=pdf.status_code, retryable=True)

        if dest.exists():
            try:
                same = dest.is_file() and dest.read_bytes() == pdf.content
            except OSError as exc:
                return CrawlerResult("failed", "Gaceta duplicate check failed; cursor retained", "gaceta",
                                     attempted_url=pdf_url, error_type=type(exc).__name__,
                                     error_message=str(exc), retryable=True)
            if not same:
                return CrawlerResult("manual_review", "Gaceta destination differs; cursor retained", "gaceta",
                                     attempted_url=pdf_url)
            duplicates += 1
            continue

        try:
            created = save_download(pdf.content, dest, pdf.url)
        except (OSError, ValueError) as exc:
            return CrawlerResult("failed", "Gaceta persistence failed; cursor retained", "gaceta",
                                 attempted_url=pdf_url, error_type=type(exc).__name__,
                                 error_message=str(exc), retryable=True)
        if not created:
            return CrawlerResult("manual_review", "Gaceta destination appeared; cursor retained", "gaceta",
                                 attempted_url=pdf_url)
        state_file.write_text(current.isoformat(), encoding="utf-8")
        return "downloaded"

    state_file.write_text(current.isoformat(), encoding="utf-8")
    return CrawlerResult("duplicate" if duplicates else "no_new_documents",
                         "Gaceta date already present" if duplicates else "Gaceta date has no PDF links",
                         "gaceta", attempted_url=page_url)

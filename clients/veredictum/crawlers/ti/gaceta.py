#!/usr/bin/env python3

import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from pathlib import Path
from datetime import date, timedelta


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

    if mode == "full":
        try:
            last = state_file.read_text(encoding="utf-8").strip()
            current = date.fromisoformat(last) + timedelta(days=1)
        except Exception:
            current = DEFAULT_START_DATE
    else:
        try:
            last = state_file.read_text(encoding="utf-8").strip()
            current = date.fromisoformat(last) + timedelta(days=1)
        except Exception:
            current = date.today()

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
    except Exception:
        state_file.write_text(current.isoformat(), encoding="utf-8")
        return "skipped"

    if r.status_code != 200 or not r.text:
        state_file.write_text(current.isoformat(), encoding="utf-8")
        return "skipped"

    pdf_links = extract_pdf_links(r.text, page_url)

    for pdf_url in pdf_links:
        name = os.path.basename(urlparse(pdf_url).path) or f"gaceta_{current.isoformat()}.pdf"
        name = safe(name if ".pdf" in name.lower() else f"{name}.pdf")
        filename = safe(f"gaceta_{current.isoformat()}_{name}")
        dest = download_dir / filename

        if dest.exists() and mode == "incremental":
            continue

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
        except Exception:
            continue

        if not is_pdf_response(pdf):
            continue

        dest.write_bytes(pdf.content)
        state_file.write_text(current.isoformat(), encoding="utf-8")
        return "downloaded"

    state_file.write_text(current.isoformat(), encoding="utf-8")
    return "skipped"

#!/usr/bin/env python3

import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from pathlib import Path

# =====================================================
# CONFIG
# =====================================================

REQUEST_TIMEOUT = 25
BASE_SEARCH_URL = "https://www.pgr.go.cr/?s={query}"

# =====================================================
# KEYWORDS (HARDCODEADAS)
# =====================================================

PRIORITY_A = [
    "Dictamen",
    "Opinión Jurídica",
    "Pronunciamiento",
    "Jurisprudencia Administrativa",
    "Criterio Institucional",
]

PRIORITY_B = [
    "C-",
    "OJ-",
    "PGR",
]

PRIORITY_C = [
    "Procuraduría de la Ética Pública",
    "Notaría del Estado",
    "Derecho Público",
]

SEARCH_KEYWORDS = PRIORITY_A + PRIORITY_B + PRIORITY_C

# =====================================================


def safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in name).strip("_")


def is_pdf_response(resp: requests.Response) -> bool:
    if not resp or resp.status_code != 200:
        return False
    ct = (resp.headers.get("Content-Type") or "").lower()
    head = resp.content[:8] if resp.content else b""
    return ("pdf" in ct or "octet-stream" in ct) and head.startswith(b"%PDF")


def extract_post_links(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/publicaciones/" in href:
            links.append(href)

    return list(dict.fromkeys(links))


def extract_pdf_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().endswith(".pdf"):
            links.append(urljoin(base_url, href))

    return list(dict.fromkeys(links))


def download_pdf(session, pdf_url: str, dest: Path) -> bool:
    try:
        r = session.get(
            pdf_url,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (FileForgeAI)",
                "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
                "Referer": pdf_url,
            },
        )
    except Exception:
        return False

    if not is_pdf_response(r):
        return False

    dest.write_bytes(r.content)
    return True


# =====================================================
# MAIN ENTRY
# =====================================================

def download_one(source: dict) -> str:
    """
    CRAWLER CONTRACT — OBLIGATORIO

    - Máximo 1 archivo por ejecución
    - Navegación permitida
    - Retorno inmediato tras 1 descarga
    - Si no descarga nada → "skipped"
    """

    download_dir = Path(source["download_dir"])
    state_file = Path(source["state_file"])
    mode = source.get("mode", "incremental")

    download_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()

    for keyword in SEARCH_KEYWORDS:
        search_url = BASE_SEARCH_URL.format(query=keyword.replace(" ", "+"))

        try:
            r = session.get(
                search_url,
                timeout=REQUEST_TIMEOUT,
                headers={
                    "User-Agent": "Mozilla/5.0 (FileForgeAI)",
                    "Accept": "text/html,application/xhtml+xml",
                },
            )
        except Exception:
            continue

        if r.status_code != 200 or not r.text:
            continue

        post_links = extract_post_links(r.text)
        if not post_links:
            continue

        for post_url in post_links:
            try:
                pr = session.get(
                    post_url,
                    timeout=REQUEST_TIMEOUT,
                    headers={
                        "User-Agent": "Mozilla/5.0 (FileForgeAI)",
                        "Accept": "text/html,application/xhtml+xml",
                    },
                )
            except Exception:
                continue

            if pr.status_code != 200 or not pr.text:
                continue

            pdf_links = extract_pdf_links(pr.text, post_url)
            if not pdf_links:
                continue

            for pdf_url in pdf_links:
                name = os.path.basename(urlparse(pdf_url).path)
                name = safe(name if name.lower().endswith(".pdf") else f"{name}.pdf")
                dest = download_dir / name

                if dest.exists() and mode == "incremental":
                    continue

                if download_pdf(session, pdf_url, dest):
                    state_file.write_text("done", encoding="utf-8")
                    return "downloaded"

        # si este keyword no dio resultado, pasar al siguiente

    state_file.write_text("done", encoding="utf-8")
    return "skipped"

#!/usr/bin/env python3

import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs
from pathlib import Path

REQUEST_TIMEOUT = 30


# -------------------------------------------------
# Utils
# -------------------------------------------------

def safe(name: str) -> str:
    return "".join(
        c if c.isalnum() or c in "._-" else "_" for c in name
    ).strip("_")


def slug_from_url(url: str) -> str:
    u = urlparse(url)
    netloc = u.netloc.lower().replace("www.", "").replace(".", "_")
    path = u.path.strip("/").replace("/", "_").lower()

    qs = parse_qs(u.query or "")
    root = ""
    if "RootFolder" in qs and qs["RootFolder"]:
        root = qs["RootFolder"][0]
        root = root.replace("%2f", "/").replace("%2F", "/")
        root = root.strip("/").replace("/", "_").lower()

    parts = [p for p in [netloc, path, root] if p]
    return safe("_".join(parts))[:120] or "asamblea"


def is_pdf_response(resp: requests.Response) -> bool:
    if not resp or resp.status_code != 200:
        return False
    ct = (resp.headers.get("Content-Type") or "").lower()
    head = resp.content[:8] if resp.content else b""
    return ("pdf" in ct or "octet-stream" in ct) and head.startswith(b"%PDF")


def extract_pdf_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href:
            continue
        h = href.lower()
        if h.startswith("#") or h.startswith("javascript:"):
            continue

        if ".pdf" in h:
            links.append(urljoin(base_url, href))
            continue

        if "download.aspx" in h and (
            "sourceurl=" in h or "sourceurl%3d" in h
        ):
            links.append(urljoin(base_url, href))

    # dedupe preservando orden
    seen = set()
    out = []
    for u in links:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def download_pdf(session: requests.Session, pdf_url: str, dest: Path) -> bool:
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

    try:
        dest.write_bytes(r.content)
        return True
    except Exception:
        return False


# -------------------------------------------------
# Entry point (contrato del manager)
# -------------------------------------------------

def download_one(source: dict) -> str:
    """
    Asamblea Legislativa — Round Robin estricto

    CONTRATO:
    - Usa SOLO los targets recibidos
    - 1 PDF máximo por ejecución
    - Respeta incremental
    """

    download_dir = Path(source["download_dir"])
    state_file = Path(source["state_file"])
    mode = source.get("mode", "incremental")
    targets = source.get("targets") or []

    download_dir.mkdir(parents=True, exist_ok=True)

    if not targets:
        return "skipped"

    session = requests.Session()

    for target in targets:
        base_url = target.get("url")
        if not base_url:
            continue

        lib_slug = slug_from_url(base_url)
        lib_dir = download_dir / lib_slug
        lib_dir.mkdir(parents=True, exist_ok=True)

        try:
            page = session.get(
                base_url,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (FileForgeAI)",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            )
        except Exception:
            continue

        if page.status_code != 200 or not page.text:
            continue

        pdf_links = extract_pdf_links(page.text, base_url)
        if not pdf_links:
            continue

        for pdf_url in pdf_links:
            name = os.path.basename(urlparse(pdf_url).path) or "documento.pdf"
            name = safe(name if ".pdf" in name.lower() else f"{name}.pdf")
            dest = lib_dir / name

            if dest.exists() and mode == "incremental":
                continue

            if download_pdf(session, pdf_url, dest):
                state_file.write_text("done", encoding="utf-8")
                return "downloaded"

        # si este target no dio PDF nuevo → RR sigue

    state_file.write_text("done", encoding="utf-8")
    return "skipped"

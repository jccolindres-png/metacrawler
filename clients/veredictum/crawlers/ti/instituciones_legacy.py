#!/usr/bin/env python3

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from pathlib import Path
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

    for url in base_urls:
        inst_slug = slug_from_url(url)
        inst_dir = base_download_dir / inst_slug
        inst_dir.mkdir(parents=True, exist_ok=True)

        try:
            r = session.get(url, timeout=15)
            if r.status_code != 200 or not r.text:
                continue
        except Exception:
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

            if dest.exists() and mode == "incremental":
                continue

            try:
                pdf = session.get(pdf_url, timeout=20)
                if not _is_pdf_response(pdf):
                    continue

                dest.write_bytes(pdf.content)
                state_file.write_text("done", encoding="utf-8")
                return "downloaded"

            except Exception:
                continue

        # esta URL no dio PDF → pasar a la siguiente

    state_file.write_text("done", encoding="utf-8")
    return "skipped"

#!/usr/bin/env python3

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from pathlib import Path


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
        last_id = int(state_file.read_text(encoding="utf-8").strip())
    except Exception:
        last_id = 0

    # 🔒 SOLO un ID por ejecución
    current_id = last_id + 1
    url = base_url + FALLO_PATH + str(current_id)

    try:
        page = requests.get(url, timeout=15)
    except Exception:
        state_file.write_text(str(current_id), encoding="utf-8")
        return "skipped"

    if page.status_code != 200 or not page.text:
        state_file.write_text(str(current_id), encoding="utf-8")
        return "skipped"

    soup = BeautifulSoup(page.text, "html.parser")

    link = soup.find(
        "a",
        href=True,
        string=lambda t: t and "PDF" in t.upper()
    )

    if not link:
        state_file.write_text(str(current_id), encoding="utf-8")
        return "skipped"

    pdf_url = urljoin(url + "/", link["href"])
    filename = f"fallo_{current_id}.pdf"
    dest = download_dir / filename

    if dest.exists() and mode == "incremental":
        state_file.write_text(str(current_id), encoding="utf-8")
        return "skipped"

    try:
        pdf = requests.get(pdf_url, timeout=20)
    except Exception:
        state_file.write_text(str(current_id), encoding="utf-8")
        return "skipped"

    if not _is_pdf_response(pdf):
        state_file.write_text(str(current_id), encoding="utf-8")
        return "skipped"

    dest.write_bytes(pdf.content)
    state_file.write_text(str(current_id), encoding="utf-8")
    return "downloaded"

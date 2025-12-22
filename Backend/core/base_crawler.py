#!/usr/bin/env python3

import requests
from pathlib import Path


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
    - SOLO PDFs reales
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

    url = base_urls[0]

    try:
        r = requests.get(
            url,
            timeout=20,
            allow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (FileForgeAI)",
                "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
            },
        )
    except Exception:
        return "failed"

    if not _is_pdf_response(r):
        return "skipped"

    filename = url.split("/")[-1] or "documento.pdf"
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"

    dest = download_dir / filename

    if dest.exists() and mode == "incremental":
        return "skipped"

    try:
        dest.write_bytes(r.content)
        state_file.write_text("done", encoding="utf-8")
        return "downloaded"
    except Exception:
        return "failed"

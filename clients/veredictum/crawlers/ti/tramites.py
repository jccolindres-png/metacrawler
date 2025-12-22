#!/usr/bin/env python3

import os
import requests
from pathlib import Path
from urllib.parse import urlparse
from datetime import date

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


def download_one(source: dict) -> str:
    """
    CRAWLER CONTRACT — OBLIGATORIO

    - Máximo 1 archivo por ejecución
    - No crawling HTML
    - URLs predecibles
    - Retorno inmediato tras 1 descarga
    - Si no descarga nada → "skipped"
    """

    base_urls = source.get("base_urls") or []
    if not base_urls:
        return "skipped"

    download_dir = Path(source["download_dir"])
    state_file = Path(source["state_file"])
    mode = source.get("mode", "incremental")

    download_dir.mkdir(parents=True, exist_ok=True)

    # estado = índice de patrón
    try:
        idx = int(state_file.read_text(encoding="utf-8").strip())
    except Exception:
        idx = 0

    # patrones conocidos de Trámites Costa Rica
    patterns = [
        "MINAE/manual-2025-v2.pdf",
        "MINAE/reglamento-2025.pdf",
        "MSP/manual-2024.pdf",
        "SALUD/procedimiento-2024.pdf",
        "MOPT/manual-2023.pdf",
        "MEIC/reglamento-2024.pdf",
        "HACIENDA/manual-2024.pdf",
    ]

    if idx >= len(patterns):
        return "skipped"

    base_url = base_urls[0].rstrip("/")
    rel_path = patterns[idx]
    pdf_url = f"{base_url}/pub/tramites/{rel_path}"

    session = requests.Session()

    try:
        r = session.get(
            pdf_url,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Metacrawler)",
                "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
            },
        )
    except Exception:
        state_file.write_text(str(idx + 1), encoding="utf-8")
        return "skipped"

    if not is_pdf_response(r):
        state_file.write_text(str(idx + 1), encoding="utf-8")
        return "skipped"

    name = os.path.basename(urlparse(pdf_url).path)
    today = date.today().isoformat()
    filename = safe(f"tramites_{today}_{name}")
    dest = download_dir / filename

    if dest.exists() and mode == "incremental":
        state_file.write_text(str(idx + 1), encoding="utf-8")
        return "skipped"

    dest.write_bytes(r.content)
    state_file.write_text(str(idx + 1), encoding="utf-8")
    return "downloaded"

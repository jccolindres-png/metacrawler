#!/usr/bin/env python3

import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs
from pathlib import Path
from core.results import CrawlerResult
from core.source_sidecar import save_download

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


def download_pdf(session: requests.Session, pdf_url: str, dest: Path, source_root: Path):
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
    except requests.RequestException as exc:
        return CrawlerResult("failed", "Asamblea PDF request failed; cursor retained", "asamblea",
                             attempted_url=pdf_url, http_status=getattr(getattr(exc, "response", None), "status_code", None),
                             error_type=type(exc).__name__, error_message=str(exc), retryable=True)

    if r.status_code != 200:
        return CrawlerResult("failed", "Asamblea PDF HTTP failure; cursor retained", "asamblea",
                             attempted_url=pdf_url, http_status=r.status_code,
                             error_type="HTTPError", error_message=f"HTTP {r.status_code}", retryable=True)
    if not is_pdf_response(r):
        return CrawlerResult("invalid_document", "invalid Asamblea PDF; cursor retained", "asamblea",
                             attempted_url=pdf_url, http_status=r.status_code, retryable=True)

    try:
        outcome = save_download(r.content, dest, r.url,
                                source_root=source_root, return_outcome=True)
    except (OSError, ValueError) as exc:
        return CrawlerResult("failed", "Asamblea persistence failed; cursor retained", "asamblea",
                             attempted_url=pdf_url, error_type=type(exc).__name__,
                             error_message=str(exc), retryable=True)
    if outcome.status == "duplicate":
        return CrawlerResult("duplicate", "Asamblea PDF content already acquired", "asamblea",
                             attempted_url=pdf_url, downloaded_path=str(outcome.path),
                             content_hash=outcome.content_hash)
    return "downloaded"


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
    first_failure = None
    duplicate = None

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
        except requests.RequestException as exc:
            first_failure = first_failure or CrawlerResult(
                "failed", "Asamblea page request failed; cursor retained", "asamblea",
                attempted_url=base_url, http_status=getattr(getattr(exc, "response", None), "status_code", None),
                error_type=type(exc).__name__, error_message=str(exc), retryable=True)
            continue

        if page.status_code != 200:
            first_failure = first_failure or CrawlerResult(
                "failed", "Asamblea page HTTP failure; cursor retained", "asamblea",
                attempted_url=base_url, http_status=page.status_code,
                error_type="HTTPError", error_message=f"HTTP {page.status_code}", retryable=True)
            continue
        if not page.text:
            first_failure = first_failure or CrawlerResult(
                "site_changed", "empty Asamblea page; cursor retained", "asamblea",
                attempted_url=base_url, http_status=page.status_code, retryable=True)
            continue

        pdf_links = extract_pdf_links(page.text, base_url)
        if not pdf_links:
            continue

        for pdf_url in pdf_links:
            name = os.path.basename(urlparse(pdf_url).path) or "documento.pdf"
            name = safe(name if ".pdf" in name.lower() else f"{name}.pdf")
            dest = lib_dir / name

            outcome = download_pdf(session, pdf_url, dest, download_dir)
            if outcome == "downloaded":
                state_file.write_text("done", encoding="utf-8")
                return "downloaded"
            if isinstance(outcome, CrawlerResult):
                if outcome.status == "duplicate":
                    duplicate = outcome
                else:
                    first_failure = first_failure or outcome

        # si este target no dio PDF nuevo → RR sigue

    if first_failure:
        return first_failure
    state_file.write_text("done", encoding="utf-8")
    return duplicate or "skipped"

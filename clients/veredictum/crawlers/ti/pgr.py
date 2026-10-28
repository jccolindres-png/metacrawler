"""Download PDF publications from the PGR institutional archive."""

import hashlib
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from core.results import CrawlerResult
from core.source_sidecar import save_download

ARCHIVE_URL = "https://www.pgr.go.cr/publicaciones/"
TIMEOUT = 25
HEADERS = {"User-Agent": "MetaCrawler/1.0"}


def _read_state(path):
    try:
        raw = path.read_text(encoding="utf-8").strip()
        data = {} if raw in ("", "{}", "done") else json.loads(raw)
    except FileNotFoundError:
        data = {}
    if not isinstance(data, dict):
        raise ValueError("PGR state must be an object")
    state = {"page_url": ARCHIVE_URL, "post_index": 0, "pdf_index": 0,
             "seen_posts": [], "seen_pdfs": []}
    state.update(data)
    if (urlparse(state["page_url"]).netloc != "www.pgr.go.cr"
            or any(not isinstance(state[key], int) or state[key] < 0
                   for key in ("post_index", "pdf_index"))
            or any(not isinstance(state[key], list) for key in ("seen_posts", "seen_pdfs"))):
        raise ValueError("invalid PGR state")
    return state


def _save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".pgr-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def extract_post_links(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for article in soup.select("article.post"):
        anchor = article.select_one("h2 a[href], h3 a[href], .post-links a[href]")
        if anchor:
            link = urljoin(base_url, anchor["href"].strip())
            if urlparse(link).netloc == "www.pgr.go.cr":
                links.append(link)
    return list(dict.fromkeys(links))


def extract_next_page(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    anchor = soup.select_one("a.next_page[href], a[rel=next][href]")
    if anchor:
        link = urljoin(base_url, anchor["href"].strip())
        if urlparse(link).netloc == "www.pgr.go.cr" and link != base_url:
            return link
    return None


def extract_pdf_links(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    links = []
    content = soup.find("main") or soup
    for anchor in content.select("a[href]"):
        link = urljoin(base_url, anchor["href"].strip())
        if urlparse(link).scheme == "https" and urlparse(link).path.lower().endswith(".pdf"):
            links.append(link)
    return list(dict.fromkeys(links))


def _get(session, url):
    response = session.get(url, timeout=TIMEOUT, headers=HEADERS)
    if response.status_code != 200 or not response.content:
        raise requests.HTTPError(f"HTTP {response.status_code} or empty response", response=response)
    return response


def _failed(exc, url):
    response = getattr(exc, "response", None)
    return CrawlerResult("failed", "PGR request failed; cursor retained", "pgr",
                         attempted_url=url, http_status=getattr(response, "status_code", None),
                         error_type=type(exc).__name__, error_message=str(exc), retryable=True)


def _save_failed(exc, url):
    return CrawlerResult("failed", "PGR persistence failed; cursor retained", "pgr",
                         attempted_url=url, error_type=type(exc).__name__,
                         error_message=str(exc), retryable=True)


def _filename(url):
    stem = "".join(c if c.isalnum() or c in "._-" else "_" for c in Path(urlparse(url).path).stem)[:100]
    return f"{stem or 'publicacion'}_{hashlib.sha256(url.encode()).hexdigest()[:12]}.pdf"


def download_one(source):
    """Inspect one archive page and publish no more than one PDF."""
    directory = Path(source["download_dir"])
    state_file = Path(source["state_file"])
    directory.mkdir(parents=True, exist_ok=True)
    try:
        state = _read_state(state_file)
    except (OSError, ValueError, TypeError) as exc:
        return CrawlerResult("manual_review", "invalid PGR cursor", "pgr",
                             error_type=type(exc).__name__, error_message=str(exc))
    session = requests.Session()
    page_url = state["page_url"]
    try:
        page = _get(session, page_url)
    except requests.RequestException as exc:
        return _failed(exc, page_url)
    posts = extract_post_links(page.text, page.url)
    next_page = extract_next_page(page.text, page.url)
    if not posts:
        if page_url != ARCHIVE_URL and not next_page:
            state["page_url"] = ARCHIVE_URL
            state["post_index"], state["pdf_index"] = 0, 0
            _save_state(state_file, state)
            return CrawlerResult("no_new_documents", "PGR archive ended", "pgr",
                                 attempted_url=page.url)
        return CrawlerResult("site_changed", "PGR archive has no publication entries", "pgr",
                             attempted_url=page.url, retryable=True)
    for index in range(state["post_index"], len(posts)):
        post_url = posts[index]
        if post_url in state["seen_posts"]:
            state["post_index"], state["pdf_index"] = index + 1, 0
            _save_state(state_file, state)
            continue
        try:
            post = _get(session, post_url)
        except requests.RequestException as exc:
            return _failed(exc, post_url)
        pdfs = extract_pdf_links(post.text, post.url)
        start = state["pdf_index"] if index == state["post_index"] else 0
        for pdf_index in range(start, len(pdfs)):
            pdf_url = pdfs[pdf_index]
            legacy = directory / Path(urlparse(pdf_url).path).name
            dest = directory / _filename(pdf_url)
            if pdf_url in state["seen_pdfs"] or legacy.exists() or dest.exists():
                if pdf_url not in state["seen_pdfs"]:
                    state["seen_pdfs"].append(pdf_url)
                state["post_index"], state["pdf_index"] = index, pdf_index + 1
                _save_state(state_file, state)
                continue
            try:
                pdf = _get(session, pdf_url)
            except requests.RequestException as exc:
                return _failed(exc, pdf_url)
            if not pdf.content.startswith(b"%PDF") or b"%%EOF" not in pdf.content[-2048:]:
                return CrawlerResult("invalid_document", "invalid PGR PDF; cursor retained", "pgr",
                                     attempted_url=pdf_url, http_status=pdf.status_code, retryable=True)
            try:
                created = save_download(pdf.content, dest, pdf.url)
            except (OSError, ValueError) as exc:
                return _save_failed(exc, pdf_url)
            if not created:
                return CrawlerResult("manual_review", "PGR destination appeared; cursor retained", "pgr",
                                     attempted_url=pdf_url)
            state["seen_pdfs"].append(pdf_url)
            state["post_index"], state["pdf_index"] = index, pdf_index + 1
            _save_state(state_file, state)
            return "downloaded"
        state["seen_posts"].append(post_url)
        state["post_index"], state["pdf_index"] = index + 1, 0
        _save_state(state_file, state)
    state["page_url"] = next_page or ARCHIVE_URL
    state["post_index"], state["pdf_index"] = 0, 0
    _save_state(state_file, state)
    return CrawlerResult("no_new_documents", "PGR archive page completed", "pgr",
                         attempted_url=page.url)

"""Write original download bytes and their observed provenance without overwriting files."""

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from core.utils.dedupe import acquire


def sidecar_path(document_path):
    return Path(str(document_path) + ".source.json")


def _provenance(data, source_url, downloaded_at_utc=None):
    if not isinstance(data, bytes):
        raise TypeError("downloaded bytes are required")
    try:
        parsed_url = urlsplit(source_url) if isinstance(source_url, str) else None
    except ValueError:
        parsed_url = None
    if parsed_url is None or parsed_url.scheme not in ("http", "https") or not parsed_url.hostname:
        raise ValueError("the final response URL is required for provenance")
    timestamp = downloaded_at_utc or datetime.now(timezone.utc).isoformat()
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("download timestamp must be UTC")
    return {"source_url": source_url, "downloaded_at_utc": timestamp,
            "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}


def _stage(directory, payload):
    fd, temporary = tempfile.mkstemp(prefix=".source-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        os.unlink(temporary)
        raise
    return temporary


def _sync_directory(directory):
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_sidecar(document_path, data, source_url, downloaded_at_utc=None):
    """Publish a sidecar exclusively; an existing matching sidecar is preserved."""
    document = Path(document_path)
    provenance = _provenance(data, source_url, downloaded_at_utc)
    if not document.is_file() or hashlib.sha256(document.read_bytes()).hexdigest() != provenance["sha256"]:
        raise ValueError("document bytes differ from the provenance")
    sidecar = sidecar_path(document)
    if sidecar.exists():
        existing = json.loads(sidecar.read_text(encoding="utf-8"))
        recorded = _provenance(data, existing.get("source_url"), existing.get("downloaded_at_utc"))
        if existing != recorded:
            raise ValueError("existing sidecar conflicts with document bytes")
        return sidecar
    payload = (json.dumps(provenance, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    temporary = _stage(document.parent, payload)
    try:
        os.link(temporary, sidecar)
        _sync_directory(document.parent)
    finally:
        os.unlink(temporary)
    return sidecar


def _publish_download(data, document_path, source_url):
    """Publish new bytes and sidecar without replacing either file."""
    provenance = _provenance(data, source_url)
    document = Path(document_path)
    document.parent.mkdir(parents=True, exist_ok=True)
    sidecar = sidecar_path(document)
    if document.exists() or sidecar.exists():
        return False
    temporary = _stage(document.parent, data)
    created = False
    try:
        try:
            os.link(temporary, document)
            created = True
        except FileExistsError:
            return False
        try:
            write_sidecar(document, data, source_url, provenance["downloaded_at_utc"])
            _sync_directory(document.parent)
        except BaseException:
            if created:
                sidecar.unlink(missing_ok=True)
                document.unlink()
            raise
        return True
    finally:
        os.unlink(temporary)


def save_download(data, document_path, source_url, *, source_root=None, return_outcome=False):
    """Acquire content in one source scope, preserving the boolean legacy API."""
    _provenance(data, source_url)
    document = Path(document_path)
    root = Path(source_root) if source_root is not None else document.parent
    outcome = acquire(data, document, root,
                      lambda selected: _publish_download(data, selected, source_url))
    return outcome if return_outcome else outcome.status == "downloaded"

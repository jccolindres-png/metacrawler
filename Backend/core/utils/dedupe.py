"""Content identity for one client's country/source download directory."""

import fcntl
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Acquisition:
    status: str
    path: Path
    content_hash: str


def _file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as document:
        for block in iter(lambda: document.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _matching_document(root, digest):
    # Files, including older downloads without sidecars, are authoritative.
    # Rechecking also recovers from a crash before index registration.
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink() and path.suffix.lower() == ".pdf":
            if _file_hash(path) == digest:
                return path
    return None


def _available_name(destination, digest):
    if not destination.exists():
        return destination
    stem, suffix = destination.stem, destination.suffix
    for index in range(1000):
        marker = digest[:16] if index == 0 else f"{digest[:16]}_{index}"
        candidate = destination.with_name(f"{stem}_{marker}{suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"no unused name for {destination}")


def _record(root, digest, destination, size):
    index = root / ".dedupe_store.json"
    if index.exists():
        store = json.loads(index.read_text(encoding="utf-8"))
        if not isinstance(store, dict) or not isinstance(store.get("hashes"), dict):
            raise ValueError("invalid deduplication index")
    else:
        store = {"meta": {"schema_version": "1.0"}, "hashes": {}}
    store["hashes"][digest] = {
        "first_seen": datetime.now(timezone.utc).isoformat(),
        "path": str(destination.relative_to(root)), "size": size,
    }
    store["meta"]["last_updated"] = datetime.now(timezone.utc).isoformat()
    fd, temporary = tempfile.mkstemp(prefix=".dedupe-", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(store, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, index)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def acquire(data, destination, source_root, publish):
    """Deduplicate by bytes and publish under an exclusive per-source lock."""
    if not isinstance(data, bytes):
        raise TypeError("downloaded bytes are required")
    root = Path(source_root).resolve()
    destination = Path(destination).resolve()
    if not destination.is_relative_to(root):
        raise ValueError("destination must belong to its source directory")
    root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    with (root / ".dedupe.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        existing = _matching_document(root, digest)
        if existing is not None:
            return Acquisition("duplicate", existing, digest)
        selected = _available_name(destination, digest)
        if not publish(selected):
            raise FileExistsError(f"destination appeared: {selected}")
        try:
            _record(root, digest, selected, len(data))
        except BaseException:
            from core.source_sidecar import sidecar_path
            sidecar_path(selected).unlink(missing_ok=True)
            selected.unlink(missing_ok=True)
            raise
        return Acquisition("downloaded", selected, digest)


def save_pdf_if_unique(pdf_bytes: bytes, dest_path: str, source_url: str | None = None) -> bool:
    """Compatibility API; new callers should use source_sidecar.save_download."""
    if source_url is not None:
        from core.source_sidecar import save_download
        return save_download(pdf_bytes, dest_path, source_url)

    def publish_raw(destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".dedupe-", dir=destination.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(pdf_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temporary, destination)
            return True
        finally:
            os.unlink(temporary)

    outcome = acquire(pdf_bytes, dest_path, Path(dest_path).parent, publish_raw)
    return outcome.status == "downloaded"

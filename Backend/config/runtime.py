import os
import tempfile
from pathlib import Path

DEFAULT_DATA_ROOT = Path("/home/ubuntu/metacrawler/downloads")


class RuntimeConfigError(RuntimeError):
    pass


def get_data_root(*, require_exists=False, require_writable=False) -> Path:
    value = os.environ.get("METACRAWLER_DATA_ROOT")
    root = Path(value).expanduser() if value else DEFAULT_DATA_ROOT
    if require_exists and not root.is_dir():
        raise RuntimeConfigError(f"METACRAWLER_DATA_ROOT does not exist or is not a directory: {root}")
    if require_writable:
        if not root.is_dir():
            raise RuntimeConfigError(f"METACRAWLER_DATA_ROOT is not writable: {root}")
        try:
            fd, probe = tempfile.mkstemp(prefix=".metacrawler-write-test-", dir=root)
            os.close(fd)
            os.unlink(probe)
        except OSError as exc:
            raise RuntimeConfigError(f"METACRAWLER_DATA_ROOT is not writable: {root}: {exc}") from exc
    return root.resolve()


def validate_data_root() -> Path:
    return get_data_root(require_exists=True, require_writable=True)

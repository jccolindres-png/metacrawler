import os
from pathlib import Path

# ==================================================
# METACRAWLER — PATH CONFIGURATION (SINGLE SOURCE)
# ==================================================

# ==================================================
# ENV VARS (con fallback seguro)
# ==================================================

def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)

# ==================================================
# BASE PROJECT ROOT (solo código)
# ==================================================

# Backend/
BACKEND_ROOT = Path(__file__).resolve().parent.parent

# ==================================================
# METACRAWLER DATA ROOT (ÚNICO LUGAR PARA DATOS)
# ==================================================

METACRAWLER_DATA_ROOT = Path(
    _env(
        "METACRAWLER_DATA_ROOT",
        "/home/ubuntu/metacrawler/downloads"
    )
)

# ==================================================
# BASE DATA DIRS
# ==================================================

DOWNLOADS_DIR = METACRAWLER_DATA_ROOT
LOG_DIR       = METACRAWLER_DATA_ROOT / "logs"
TMP_DIR       = METACRAWLER_DATA_ROOT / "tmp"

# ==================================================
# CLIENT / COUNTRY / CRAWLER DATA
# ==================================================

CLIENTS_DATA_DIR = METACRAWLER_DATA_ROOT / "clients"

# ==================================================
# TEMPORALES / CHECKPOINTS
# ==================================================

CHECKPOINTS_DIR = TMP_DIR / "checkpoints"
TMP_OCR_DIR     = TMP_DIR / "ocr"
TMP_TEXT_DIR    = TMP_DIR / "text"

# ==================================================
# CREACIÓN SEGURA DE DIRECTORIOS
# ==================================================

ALL_DIRS = [
    DOWNLOADS_DIR,
    LOG_DIR,
    TMP_DIR,

    CLIENTS_DATA_DIR,

    CHECKPOINTS_DIR,
    TMP_OCR_DIR,
    TMP_TEXT_DIR,
]

for path in ALL_DIRS:
    path.mkdir(parents=True, exist_ok=True)

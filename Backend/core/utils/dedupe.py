import hashlib
import json
import sys
from pathlib import Path
from datetime import datetime

# -------------------------------------------------
# Asegurar Backend como raíz importable
# -------------------------------------------------

CODE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = CODE_DIR.parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config.paths import METACRAWLER_DATA_ROOT

# =====================================================
# CONFIG
# =====================================================

# Estado del deduplicador (persistente, transversal)
DEDUPE_STORE = (
    Path(METACRAWLER_DATA_ROOT)
    / "_state"
    / "dedupe_store.json"
)

DEDUPE_STORE.parent.mkdir(parents=True, exist_ok=True)

# =====================================================
# HELPERS INTERNOS
# =====================================================

def _load_store():
    if not DEDUPE_STORE.exists():
        return {
            "meta": {
                "schema_version": "1.0",
                "last_updated": None
            },
            "hashes": {}
        }

    with open(DEDUPE_STORE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_store(store: dict):
    store["meta"]["last_updated"] = datetime.utcnow().isoformat()
    with open(DEDUPE_STORE, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2, ensure_ascii=False)


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

# =====================================================
# API PÚBLICA (MISMA FIRMA QUE LOS CRAWLERS VIEJOS)
# =====================================================

def save_pdf_if_unique(
    pdf_bytes: bytes,
    dest_path: str,
    source_url: str | None = None
) -> bool:
    """
    Guarda el PDF solo si el CONTENIDO es nuevo.

    Retorna:
        True  -> archivo guardado
        False -> duplicado (no se guardó)
    """

    content_hash = _hash_bytes(pdf_bytes)
    store = _load_store()

    # Ya existe el contenido
    if content_hash in store["hashes"]:
        return False

    # Guardar archivo
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    with open(dest, "wb") as f:
        f.write(pdf_bytes)

    # Registrar hash
    store["hashes"][content_hash] = {
        "first_seen": datetime.utcnow().isoformat(),
        "path": str(dest),
        "source_url": source_url,
        "size": len(pdf_bytes)
    }

    _save_store(store)
    return True

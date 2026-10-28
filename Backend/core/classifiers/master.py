import importlib
import sys
from pathlib import Path
from urllib.parse import urlparse
from core.client_provider import provider_for


# -------------------------------------------------
# Asegurar root del proyecto como importable
# -------------------------------------------------

CODE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = CODE_DIR.parent.parent
PROJECT_ROOT = BACKEND_DIR.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class NullClassifier:
    """
    Clasificador neutro para Metacrawler.

    Garantiza el contrato mínimo esperado por bootstrap:
    devuelve siempre un dict con source_id y subfolder.
    """

    def classify(self, url: str):
        domain = urlparse(url).netloc.lower()

        # Heurística mínima y segura (la que ya tenías antes)
        if "asamblea.go.cr" in domain:
            return {"source_id": "asamblea", "subfolder": None}

        if "imprentanacional.go.cr" in domain:
            return {"source_id": "gaceta", "subfolder": None}

        if domain in ("sinalevi.go.cr", "www.sinalevi.go.cr",
                      "pgrweb.go.cr", "www.pgrweb.go.cr"):
            return {"source_id": "sinalevi", "subfolder": None}

        if "pgr.go.cr" in domain:
            return {"source_id": "pgr", "subfolder": None}

        if "poder-judicial.go.cr" in domain:
            return {"source_id": "poder_judicial", "subfolder": None}

        if "kerwa.ucr.ac.cr" in domain:
            return {"source_id": "ucr_kerwa", "subfolder": None}

        if "repositorio.una.ac.cr" in domain:
            return {"source_id": "una_repositorio", "subfolder": None}

        if "kimuk.conare.ac.cr" in domain:
            return {"source_id": "conare_kimuk", "subfolder": None}

        # Fallback real
        return {"source_id": "instituciones", "subfolder": None}


def load_classifier(client_name: str):
    """
    Intenta cargar el clasificador del cliente desde:

        clients/<client_name>/classifier.py

    Si falla, usa NullClassifier (seguro).
    """

    module_path = f"clients.{provider_for(client_name, 'classifier')}.classifier"

    try:
        module = importlib.import_module(module_path)
        return module.Classifier()
    except Exception:
        return NullClassifier()

from urllib.parse import urlparse


class Classifier:
    """
    Clasificador de FUENTES por URL.
    NO hereda de BaseClassifier porque no clasifica texto.
    """

    def classify(self, url: str):
        domain = urlparse(url).netloc.lower()

        # 🔒 Normalización crítica
        if domain.startswith("www."):
            domain = domain[4:]

        if "asamblea.go.cr" in domain:
            return {
                "source_id": "asamblea",
                "crawler": "asamblea",
                "subfolder": None
            }

        if "imprentanacional.go.cr" in domain:
            return {
                "source_id": "gaceta",
                "crawler": "gaceta",
                "subfolder": None
            }

        if "pgr.go.cr" in domain or "pgrweb.go.cr" in domain:
            return {
                "source_id": "pgr",
                "crawler": "pgr",
                "subfolder": None
            }

        if "poder-judicial.go.cr" in domain:
            return {
                "source_id": "poder_judicial",
                "crawler": "poder_judicial",
                "subfolder": None
            }

        if "kerwa.ucr.ac.cr" in domain:
            return {
                "source_id": "ucr_kerwa",
                "crawler": "base",
                "subfolder": None
            }

        if "repositorio.una.ac.cr" in domain:
            return {
                "source_id": "una_repositorio",
                "crawler": "base",
                "subfolder": None
            }

        if "kimuk.conare.ac.cr" in domain:
            return {
                "source_id": "conare_kimuk",
                "crawler": "base",
                "subfolder": None
            }

        return {
            "source_id": "instituciones",
            "crawler": "instituciones",
            "subfolder": None
        }

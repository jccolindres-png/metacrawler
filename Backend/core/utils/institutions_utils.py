from urllib.parse import urlparse
from core.utils.menu_utils import select_from_columns


def derive_institution_name(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    name = netloc.replace("www.", "").split(".")[0]
    return name.upper()


def select_institutions_from_source(source: dict):
    urls = source.get("base_urls", [])
    institutions = sorted({derive_institution_name(u) for u in urls})

    print("\n🏛️ Seleccioná instituciones\n")
    chosen = select_from_columns(institutions)

    if chosen is None:
        return None

    return [
        u for u in urls
        if derive_institution_name(u) in chosen
    ]

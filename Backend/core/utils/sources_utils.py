import os
import yaml


def load_sources(sources_file):
    if not os.path.exists(sources_file):
        return []

    with open(sources_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    sources = []

    for src in data.get("sources", []):
        src_id = src.get("id")

        # ✅ instituciones (legacy o no) se maneja como source única
        if src_id in ("instituciones", "instituciones_legacy"):
            sources.append(src)
            continue

        targets = src.get("targets")

        # ❌ FIX CLAVE:
        # NO expandir targets para fuentes normales (ej: tramites)
        # Se respeta 1 source = 1 task
        sources.append(src)

    return sources

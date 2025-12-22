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

        # Caso especial: instituciones se maneja como source única
        if src_id == "instituciones":
            sources.append(src)
            continue

        targets = src.get("targets")

        # Si tiene targets, se expanden como sources independientes
        if targets:
            for t in targets:
                sources.append({
                    "id": t.get("id"),
                    "name": t.get("name"),
                    "base_urls": [t.get("url")],
                })
        else:
            sources.append(src)

    return sources

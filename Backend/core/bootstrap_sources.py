#!/usr/bin/env python3
import os
import sys
import argparse
import yaml

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 🔧 Asegurar Backend como raíz importable
BACKEND_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from classifiers.master import load_classifier

SOURCES_FILE = os.path.join(BASE_DIR, "sources.yaml")


# -------------------------------------------------
# Lector YAML robusto (formato viejo + nuevo)
# -------------------------------------------------

def read_urls(urls_file: str):
    if not os.path.exists(urls_file):
        raise RuntimeError(f"No existe el archivo: {urls_file}")

    with open(urls_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    urls = []

    # Formato NUEVO: sources -> targets -> url
    for src in data.get("sources", []):
        for tgt in src.get("targets", []):
            url = tgt.get("url")
            if isinstance(url, str):
                urls.append(url)

    # Formato VIEJO: sources -> base_urls
    if not urls:
        for src in data.get("sources", []):
            for url in src.get("base_urls", []):
                if isinstance(url, str):
                    urls.append(url)

    if not urls:
        raise RuntimeError("El YAML no contiene URLs válidas")

    return urls


# -------------------------------------------------
# Bootstrap
# -------------------------------------------------

def bootstrap(client: str, country: str | None, urls_file: str):
    print("🔧 Iniciando bootstrap (PLAN ONLY)")
    print(f"👤 Cliente : {client}")
    print(f"🌍 País    : {country if country else '(no aplica)'}")
    print(f"📄 Archivo : {urls_file}")

    classifier = load_classifier(client)
    urls = read_urls(urls_file)

    sources = {}

    # ✅ SOURCE ID CORRECTO DESDE CLASIFICADOR (NO DESDE EL NOMBRE DEL PAÍS)
    source_id = (classifier.classify(urls[0]) or {}).get("source_id")

    for url in urls:
        try:
            result = classifier.classify(url) or {}
        except Exception:
            result = {}

        subfolder = result.get("subfolder")

        if source_id not in sources:
            sources[source_id] = {
                "urls": [],
                "subfolder": subfolder
            }

        sources[source_id]["urls"].append(url)

    sources_yaml = {
        "client": client,
        "country": country,
        "sources": []
    }

    for source_id, info in sources.items():
        print(f"📦 Fuente detectada: {source_id}")
        sources_yaml["sources"].append({
            "id": source_id,
            "base_urls": info["urls"],
            "subfolder": info["subfolder"]
        })

    with open(SOURCES_FILE, "w", encoding="utf-8") as f:
        yaml.dump(
            sources_yaml,
            f,
            sort_keys=False,
            allow_unicode=True
        )

    print("✅ Bootstrap completado (PLAN ONLY)")
    print("📄 sources.yaml generado correctamente")


def main():
    parser = argparse.ArgumentParser(
        description="Metacrawler Bootstrap (PLAN ONLY, sin IO)"
    )

    parser.add_argument("--client", required=True)
    parser.add_argument("--urls", required=True)
    parser.add_argument("--country", required=False, default=None)

    args = parser.parse_args()

    bootstrap(
        client=args.client,
        country=args.country,
        urls_file=os.path.abspath(args.urls)
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import os
import sys
import argparse
import tempfile
import yaml
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 🔧 Asegurar Backend como raíz importable
BACKEND_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from core.classifiers.master import load_classifier
from config.runtime import validate_data_root


# -------------------------------------------------
# Lector YAML robusto (formato viejo + nuevo)
# -------------------------------------------------

def read_urls(urls_file: str):
    if not os.path.exists(urls_file):
        raise RuntimeError(f"No existe el archivo: {urls_file}")

    with open(urls_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    urls = []

    for src in data.get("sources", []):
        for tgt in src.get("targets", []):
            url = tgt.get("url")
            if isinstance(url, str):
                urls.append(url)

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

def plan_path(client: str, country: str, data_root=None):
    root = data_root or validate_data_root()
    return os.path.join(str(root), client, country, "_plans", "sources.yaml")


def bootstrap(client: str, country: str | None, urls_file: str, output_file=None):
    print("🔧 Iniciando bootstrap (PLAN ONLY)")
    print(f"👤 Cliente : {client}")
    print(f"🌍 País    : {country if country else '(no aplica)'}")
    print(f"📄 Archivo : {urls_file}")

    classifier = load_classifier(client)
    urls = read_urls(urls_file)

    sources = {}

    for url in urls:
        try:
            result = classifier.classify(url) or {}
        except Exception:
            result = {}

        source_id = result.get("source_id")
        subfolder = result.get("subfolder")

        # 🔴 FIX CLAVE: NO colapsar trámites dentro de instituciones
        parsed = urlparse(url)
        if parsed.netloc == "www.tramites.go.cr":
            source_id = "tramites"

        if not source_id:
            continue

        if source_id not in sources:
            sources[source_id] = {
                "urls": [],
                "targets": [],
                "subfolder": subfolder
            }

        sources[source_id]["urls"].append(url)
        sources[source_id]["targets"].append({"url": url})

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
            "targets": info["targets"],
            "subfolder": info["subfolder"]
        })

    if not country:
        raise RuntimeError("country is required for a scoped source plan")
    output_file = output_file or plan_path(client, country)
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".sources.", suffix=".yaml", dir=os.path.dirname(output_file))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(sources_yaml, f, sort_keys=False, allow_unicode=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, output_file)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

    print("✅ Bootstrap completado (PLAN ONLY)")
    print(f"📄 Plan generado: {output_file}")
    return output_file


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

#!/usr/bin/env python3
import os
import sys
import argparse
import json
import yaml

# -------------------------------------------------
# Paths base
# -------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 🔧 Backend como módulo importable (proceso actual)
BACKEND_DIR = os.path.join(BASE_DIR, "Backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# -------------------------------------------------
# Clients dir (estructura nueva)
# -------------------------------------------------

CLIENTS_DIR = os.path.join(BASE_DIR, "clients")
if not os.path.isdir(CLIENTS_DIR):
    CLIENTS_DIR = None

ITU_MAP_FILE = os.path.join(BACKEND_DIR, "core", "config", "itu_map.yaml")

# -------------------------------------------------
# Imports desde utils (estructura real)
# -------------------------------------------------

from core.utils.menu_utils import (
    print_menu,
    select_multiple,
)

from core.utils.sources_utils import (
    load_sources,
)

from core.utils.institutions_utils import (
    derive_institution_name,
    select_from_columns,
)

from core.crawler_manager import CrawlerManager
from core.bootstrap_sources import bootstrap
from config.runtime import validate_data_root, RuntimeConfigError
from core.utils.round_robin import RoundRobinScheduler

# -------------------------------------------------
# Utilidades locales
# -------------------------------------------------

def list_clients():
    if CLIENTS_DIR is None:
        print("❌ No se encontró carpeta de clientes.")
        return []

    clients = [
        name for name in sorted(os.listdir(CLIENTS_DIR))
        if os.path.isdir(os.path.join(CLIENTS_DIR, name))
        and not name.startswith("__")
    ]

    if not clients:
        return ["default"]

    return clients


def list_url_files(client):
    if client == "default":
        return [
            f for f in sorted(os.listdir(CLIENTS_DIR))
            if f.endswith("-urls.txt")
        ]

    client_dir = os.path.join(CLIENTS_DIR, client)
    if not os.path.isdir(client_dir):
        return []

    return [
        f for f in sorted(os.listdir(client_dir))
        if f.endswith("-urls.txt")
    ]


def extract_country_from_filename(filename):
    import yaml

    if not os.path.exists(ITU_MAP_FILE):
        return None

    with open(ITU_MAP_FILE, "r", encoding="utf-8") as f:
        itu_map = yaml.safe_load(f) or {}

    if "-" not in filename:
        return None

    prefix = filename.split("-")[0]
    return prefix if prefix in itu_map else None


def list_crawlers(client, country):
    crawlers_dir = os.path.join(
        CLIENTS_DIR,
        client,
        "crawlers",
        country
    )

    if not os.path.isdir(crawlers_dir):
        return []

    return sorted([
        os.path.splitext(f)[0]
        for f in os.listdir(crawlers_dir)
        if f.endswith(".py")
        and not f.startswith("_")
        and f != "__init__.py"
    ])


# -------------------------------------------------
# Main
# -------------------------------------------------

def run():
    print("🚀 Metacrawler Runner")
    root = validate_data_root()
    print(f"Effective data root: {root}")

    # -------- Cliente --------
    clients = list_clients()
    print_menu("📦 Seleccioná un cliente", clients)
    client = select_multiple(clients)

    if not client or len(client) != 1:
        print("❌ Debés seleccionar un solo cliente")
        sys.exit(1)

    client = client[0]

    # -------- Países --------
    while True:
        url_files = list_url_files(client)
        print_menu("📄 Seleccioná archivos de URLs (países)", url_files)
        selected_files = select_multiple(url_files)

        if selected_files is None:
            continue
        if not selected_files:
            print("❌ No se seleccionó ningún archivo")
            continue
        break

    # -------- Loop por país --------
    for url_file in selected_files:
        urls_path = (
            os.path.join(CLIENTS_DIR, url_file)
            if client == "default"
            else os.path.join(CLIENTS_DIR, client, url_file)
        )

        country = extract_country_from_filename(url_file)

        print(f"\n⚙️ Ejecutando bootstrap para {url_file}...\n")

        generated_plan = bootstrap(client, country, urls_path)
        sources = load_sources(generated_plan)

        print("\n¿Qué querés correr?\n")
        print("[A] Todas las fuentes")
        print("[S] Seleccionar fuentes")
        print("[Q] Salir\n")

        choice = input("Opción: ").strip().lower()
        if choice == "q":
            sys.exit(0)

        crawler_ids = list_crawlers(client, country)

        if not crawler_ids:
            print("❌ No se encontraron crawlers para este país.")
            sys.exit(1)

        selected_sources = sources

        if choice == "s":
            print_menu("📦 Seleccioná fuentes", crawler_ids)
            picked = select_multiple(crawler_ids)
            if picked is None:
                continue

            selected_sources = [
                s for s in sources
                if s.get("id") in picked
            ]

        # ---- SUBMENÚ SOLO SI instituciones_legacy FUE SELECCIONADA ----
        for src in selected_sources:
            if src["id"] != "instituciones_legacy":
                continue

            urls = src.get("base_urls", [])
            institutions = sorted({derive_institution_name(u) for u in urls})

            print("\n🏛️ Seleccioná instituciones\n")
            chosen = select_from_columns(institutions)
            if chosen is None:
                continue

            src["targets"] = [
                u for u in urls
                if derive_institution_name(u) in chosen
            ]

        manager = CrawlerManager(
            client=client,
            country=country,
            only_source=None,
            plan_path=generated_plan,
        )

        manager.sources_override = selected_sources
        manager.run()


def _discover():
    return {client: [extract_country_from_filename(f) for f in list_url_files(client)
                     if extract_country_from_filename(f)] for client in list_clients()}


def command(args):
    root = validate_data_root()
    print(f"Effective data root: {root}")
    if args.command == "validate-config":
        print("Configuration valid and data root writable")
        return
    if args.command == "plan":
        url_file = os.path.join(CLIENTS_DIR, args.client, f"{args.country}-urls.txt")
        path = bootstrap(args.client, args.country, url_file)
        print(path)
        return
    if args.command == "status":
        report = {"clients": _discover(), "data_root": str(root), "writable": os.access(root, os.W_OK), "runtime": {}}
        for client, countries in report["clients"].items():
            for country in countries:
                base = root / client / country
                state_file = base / "_state" / "round_robin.yaml"
                plan = base / "_plans" / "sources.yaml"
                scheduler, scheduler_error = None, None
                if state_file.exists():
                    try: scheduler = yaml.safe_load(state_file.read_text())
                    except Exception as exc: scheduler_error = f"malformed: {exc}"
                report["runtime"][f"{client}/{country}"] = {
                    "plan": str(plan) if plan.exists() else None,
                    "scheduler": scheduler,
                    "scheduler_error": scheduler_error,
                    "pending_retries": [t for t in (scheduler or {}).get("tasks", []) if t.get("retry_at")],
                }
        dedupe = root / "_state" / "dedupe_store.json"
        try: report["dedupe_entries"] = len(json.loads(dedupe.read_text()).get("hashes", {})) if dedupe.exists() else 0
        except Exception as exc: report["dedupe_error"] = str(exc)
        print(json.dumps(report, indent=2, default=str))
        return
    if args.command == "reset-state":
        if not args.yes: raise RuntimeError("reset-state requires --yes")
        state = root / args.client / args.country / "_state" / "round_robin.yaml"
        RoundRobinScheduler(state, args.client, args.country).reset()
        print(f"Reset scheduler state: {state}")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("validate-config")
    sub.add_parser("status")
    plan_cmd = sub.add_parser("plan"); plan_cmd.add_argument("--client", required=True); plan_cmd.add_argument("--country", required=True)
    reset = sub.add_parser("reset-state"); reset.add_argument("--client", required=True); reset.add_argument("--country", required=True); reset.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    try:
        command(args) if args.command else run()
    except RuntimeConfigError as exc:
        parser.error(str(exc))


if __name__ == "__main__": main()

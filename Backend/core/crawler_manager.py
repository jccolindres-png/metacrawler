#!/usr/bin/env python3

import yaml
import time
import sys
from pathlib import Path
from datetime import datetime

# -------------------------------------------------
# Asegurar Backend como raíz importable
# -------------------------------------------------

CODE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = CODE_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from core.crawler_loader import load_crawler
from core.utils.round_robin import RoundRobinScheduler
from config.paths import METACRAWLER_DATA_ROOT

# =====================================================
# PATHS
# =====================================================

SOURCES_FILE = CODE_DIR / "sources.yaml"

# =====================================================
# MANAGER
# =====================================================

class CrawlerManager:
    """
    CRAWLER MANAGER — CONTRATO FORZADO

    - El manager manda
    - Máximo 1 acción efectiva por crawler por ejecución
    - El crawler NO decide ritmo ni volumen
    """

    def __init__(self, client: str, country: str, mode="incremental", only_source=None):
        self.client = client
        self.country = country.lower()
        self.mode = mode
        self.only_source = only_source
        self.start_time = datetime.utcnow()

        self.root_dir = Path(METACRAWLER_DATA_ROOT) / self.client / self.country
        self.root_dir.mkdir(parents=True, exist_ok=True)

        self.state_dir = self.root_dir / "_state"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.stats = {
            "attempted": 0,
            "downloaded": 0,
            "failed": 0,
            "skipped": 0,
        }

        self.log_file = None

        self.rr = RoundRobinScheduler(
            self.state_dir / "round_robin.yaml"
        )

    # -------------------------------------------------

    def log(self, msg: str):
        line = f"[{datetime.utcnow().isoformat()}] {msg}"
        print(line)
        if self.log_file:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    # -------------------------------------------------

    def load_sources(self):
        if not SOURCES_FILE.exists():
            raise RuntimeError("sources.yaml no existe")

        with open(SOURCES_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return data.get("sources", [])

    # -------------------------------------------------

    def select_sources_interactively(self, sources):
        print("\n📦 Fuentes disponibles:\n")

        for idx, src in enumerate(sources, start=1):
            print(f"[{idx}] {src.get('id')}")

        print("\n[A] Todas")
        print("[B] Volver")
        print("[Q] Salir\n")

        choice = input("Seleccioná fuentes (ej: 1,3 o A): ").strip().lower()

        if choice == "q":
            exit(0)

        if choice == "b":
            return []

        if choice == "a":
            return sources

        selected = []
        for part in choice.split(","):
            if part.strip().isdigit():
                i = int(part.strip()) - 1
                if 0 <= i < len(sources):
                    selected.append(sources[i])

        return selected

    # -------------------------------------------------

    def select_mode_interactively(self):
        print("\n⚙️ Seleccioná modo de descarga:\n")
        print("[1] Incremental (solo nuevos)")
        print("[2] Completa (bajar todo)\n")

        choice = input("Modo: ").strip()
        return "full" if choice == "2" else "incremental"

    # -------------------------------------------------

    def run(self):
        # 🔴 CLAVE: si el runner ya decidió fuentes, NO preguntar nada
        if hasattr(self, "sources_override"):
            sources = self.sources_override
        else:
            sources = self.load_sources()
            if not sources:
                print("❌ No hay fuentes para ejecutar")
                return

            if self.only_source:
                sources = [s for s in sources if s.get("id") == self.only_source]
            else:
                sources = self.select_sources_interactively(sources)

        if not sources:
            return

        self.mode = self.select_mode_interactively()

        logs_dir = self.root_dir / "_logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        safe_ts = self.start_time.strftime("%Y%m%d_%H%M%S")
        self.log_file = logs_dir / f"crawl_{safe_ts}.log"

        tasks = []
        for source in sources:
            tasks.append({
                "source_id": source["id"],
                "targets": source.get("targets") or []
            })

        # 🔒 Siempre limpiar y reinicializar RR
        self.rr.reset()
        self.rr.bootstrap(tasks)

        self.log(
            f"🚀 Iniciando crawling RR | cliente={self.client} país={self.country} modo={self.mode}"
        )
        self.log(f"📦 Tareas totales: {len(tasks)}")

        while True:
            task = self.rr.next()
            if not task:
                break

            result = self._run_task(task)
            self.rr.update(task, result)

            time.sleep(8)

        self.finish()

    # -------------------------------------------------

    def _run_task(self, task: dict) -> str:
        """
        CONTRATO FORZADO:
        - El manager normaliza el resultado
        - Solo 'downloaded' cuenta
        - Todo lo demás es 'skipped'
        """

        source_id = task["source_id"]
        targets = task.get("targets", [])

        self.log(f"🔹 Ejecutando: {source_id}")

        crawler_module = load_crawler(
            client=self.client,
            country=self.country,
            source_id=source_id,
        )

        downloads_dir = self.root_dir / source_id
        downloads_dir.mkdir(parents=True, exist_ok=True)

        state_file = self.state_dir / f"{source_id}.json"
        if not state_file.exists():
            state_file.write_text("{}", encoding="utf-8")

        source_ctx = {
            "download_dir": str(downloads_dir),
            "state_file": str(state_file),
            "mode": self.mode,
            "targets": targets,
        }

        self.stats["attempted"] += 1

        try:
            if hasattr(crawler_module, "download_one"):
                raw_result = crawler_module.download_one(source_ctx)
            elif hasattr(crawler_module, "run"):
                raw_result = crawler_module.run(source_ctx)
            else:
                raise RuntimeError("Crawler sin entrypoint válido")

        except Exception as e:
            self.stats["failed"] += 1
            self.log(f"❌ Error {source_id}: {e}")
            return "failed"

        if raw_result == "downloaded":
            self.stats["downloaded"] += 1
            return "downloaded"

        self.stats["skipped"] += 1
        return "skipped"

    # -------------------------------------------------

    def finish(self):
        duration = (datetime.utcnow() - self.start_time).total_seconds()

        self.log("✅ Crawling finalizado")
        self.log(f"📊 Intentados: {self.stats['attempted']}")
        self.log(f"⬇️ Descargados: {self.stats['downloaded']}")
        self.log(f"⏭️ Omitidos: {self.stats['skipped']}")
        self.log(f"❌ Fallidos: {self.stats['failed']}")
        self.log(f"⏱️ Duración: {duration:.1f}s")

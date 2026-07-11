#!/usr/bin/env python3

import yaml
import time
import sys
import json
import uuid
import traceback
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
from core.results import CrawlerResult, normalize_result
from config.runtime import validate_data_root

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

    def __init__(self, client: str, country: str, mode="incremental", only_source=None, plan_path=None, reset_state=False):
        self.client = client
        self.country = country.lower()
        self.mode = mode
        self.only_source = only_source
        self.start_time = datetime.utcnow()
        self.run_id = str(uuid.uuid4())
        self.plan_path = Path(plan_path) if plan_path else None
        self.reset_state_requested = reset_state

        data_root = validate_data_root()
        print(f"Effective data root: {data_root}")
        self.root_dir = data_root / self.client / self.country
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
        self.jsonl_file = None

        self.rr = RoundRobinScheduler(
            self.state_dir / "round_robin.yaml", self.client, self.country
        )

    # -------------------------------------------------

    def log(self, msg: str):
        line = f"[{datetime.utcnow().isoformat()}] {msg}"
        print(line)
        if self.log_file:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def event(self, event: str, **fields):
        payload = {"timestamp": datetime.utcnow().isoformat() + "Z", "run_id": self.run_id,
                   "client": self.client, "country": self.country, "event": event, **fields}
        if self.jsonl_file:
            with open(self.jsonl_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")

    # -------------------------------------------------

    def load_sources(self):
        source_file = self.plan_path or SOURCES_FILE
        if not source_file.exists():
            raise RuntimeError(f"source plan does not exist: {source_file}")

        with open(source_file, "r", encoding="utf-8") as f:
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
        self.jsonl_file = logs_dir / f"crawl_{safe_ts}.jsonl"

        tasks = []
        self.source_configs = {}
        for source in sources:
            self.source_configs[source["id"]] = source
            tasks.append({
                "source_id": source["id"],
                "targets": source.get("targets") or []
            })

        if self.reset_state_requested:
            self.rr.reset()
        self.rr.bootstrap(tasks)

        self.log(
            f"🚀 Iniciando crawling RR | cliente={self.client} país={self.country} modo={self.mode}"
        )
        self.log(f"📦 Tareas totales: {len(self.rr.state.get('tasks', []))}")

        self.event("run_start", scheduler_decision="bounded_cycle", task_count=len(tasks))
        for _ in range(len(tasks)):
            task = self.rr.next()
            if not task:
                break
            self.event("task_start", source=task["source_id"], scheduler_decision="selected")
            result = self._run_task(task)
            self.rr.update(task, result.to_dict())

        self.finish()

    # -------------------------------------------------

    def _run_task(self, task: dict) -> CrawlerResult:
        source_id = task["source_id"]
        source_config = self.source_configs.get(source_id, {})
        targets = source_config.get("targets") or []

        self.log(f"🔹 Ejecutando: {source_id}")

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
            "base_urls": source_config.get("base_urls") or [],
        }

        self.stats["attempted"] += 1
        started = time.monotonic()

        try:
            crawler_module = load_crawler(client=self.client, country=self.country, source_id=source_id)
            if hasattr(crawler_module, "download_one"):
                raw_result = crawler_module.download_one(source_ctx)
            elif hasattr(crawler_module, "run"):
                raw_result = crawler_module.run(source_ctx)
            else:
                raise RuntimeError("Crawler sin entrypoint válido")

        except Exception as e:
            self.stats["failed"] += 1
            self.log(f"❌ Error {source_id}: {e}")
            result = CrawlerResult("failed", "crawler raised an exception", source_id,
                                   error_type=type(e).__name__, error_message=str(e), retryable=True)
            self.event("task_end", source=source_id, duration_seconds=time.monotonic()-started,
                       result_status=result.status, reason=result.reason, exception=traceback.format_exc(), retryable=True)
            return result

        result = normalize_result(raw_result, source_id)
        if result.status == "downloaded":
            self.stats["downloaded"] += 1
        elif result.status == "failed": self.stats["failed"] += 1
        else: self.stats["skipped"] += 1
        self.event("task_end", source=source_id, duration_seconds=time.monotonic()-started,
                   result_status=result.status, reason=result.reason, retryable=result.retryable,
                   retry_at=result.retry_at, downloaded_path=result.downloaded_path,
                   content_hash=result.content_hash)
        return result

    # -------------------------------------------------

    def finish(self):
        duration = (datetime.utcnow() - self.start_time).total_seconds()

        self.log("✅ Crawling finalizado")
        self.log(f"📊 Intentados: {self.stats['attempted']}")
        self.log(f"⬇️ Descargados: {self.stats['downloaded']}")
        self.log(f"⏭️ Omitidos: {self.stats['skipped']}")
        self.log(f"❌ Fallidos: {self.stats['failed']}")
        self.log(f"⏱️ Duración: {duration:.1f}s")
        self.event("run_end", duration_seconds=duration, stats=self.stats)

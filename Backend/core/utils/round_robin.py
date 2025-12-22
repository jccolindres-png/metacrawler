#!/usr/bin/env python3

import yaml
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional


class RoundRobinScheduler:
    """
    Round-robin persistente basado en YAML.

    - Mantiene una cola de tareas (source / target)
    - Expande fuentes con múltiples targets
    - Devuelve UNA tarea por iteración
    - Persiste estado para reanudar
    - Auditable
    """

    def __init__(self, state_file: Path):
        self.state_file = Path(state_file)
        self._init_state()

        if self.state_file.exists():
            self._load()
        else:
            self._save()

    # -------------------------------------------------

    def _init_state(self):
        self.state = {
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": None,
            "cursor": 0,
            "tasks": []
        }

    # -------------------------------------------------

    def reset(self):
        """
        Resetea COMPLETAMENTE el scheduler:
        - Borra tareas
        - Resetea cursor
        - Elimina el archivo YAML
        """
        self._init_state()
        if self.state_file.exists():
            self.state_file.unlink()
        self._save()

    # -------------------------------------------------

    def _load(self):
        with open(self.state_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            self.state.update(data)

    def _save(self):
        self.state["updated_at"] = datetime.utcnow().isoformat()
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.state, f, sort_keys=False)

    # -------------------------------------------------

    def bootstrap(self, tasks: List[Dict]):
        """
        Inicializa la cola SOLO si está vacía.

        Acepta:
        - {source_id, target_id}
        - {source_id, targets: [{id: ...}, ...]}
        """

        if self.state["tasks"]:
            return

        expanded = []

        for t in tasks:
            source_id = t["source_id"]

            # Caso 1: tarea ya atómica
            if "target_id" in t:
                expanded.append(
                    self._new_task(source_id, t.get("target_id"))
                )
                continue

            # Caso 2: fuente con múltiples targets
            targets = t.get("targets") or []
            if targets:
                for target in targets:
                    expanded.append(
                        self._new_task(source_id, target.get("id"))
                    )
            else:
                # Fuente sin targets explícitos
                expanded.append(
                    self._new_task(source_id, None)
                )

        self.state["tasks"] = expanded
        self.state["cursor"] = 0
        self._save()

    # -------------------------------------------------

    def _new_task(self, source_id: str, target_id: Optional[str]):
        return {
            "source_id": source_id,
            "target_id": target_id,
            "last_result": None,
            "last_run": None,
            "runs": 0
        }

    # -------------------------------------------------

    def next(self) -> Optional[Dict]:
        """
        Devuelve la siguiente tarea según round robin.
        """
        tasks = self.state["tasks"]
        if not tasks:
            return None

        idx = self.state["cursor"] % len(tasks)
        task = tasks[idx]

        self.state["cursor"] = (idx + 1) % len(tasks)
        self._save()

        return task

    # -------------------------------------------------

    def update(self, task: Dict, result: str):
        """
        Actualiza el estado de una tarea luego de ejecutarse.
        """
        for t in self.state["tasks"]:
            if (
                t["source_id"] == task["source_id"]
                and t.get("target_id") == task.get("target_id")
            ):
                t["last_result"] = result
                t["last_run"] = datetime.utcnow().isoformat()
                t["runs"] += 1
                break

        self._save()

    # -------------------------------------------------

    def stats(self) -> Dict:
        """
        Devuelve estado completo (para debug / auditoría).
        """
        return self.state

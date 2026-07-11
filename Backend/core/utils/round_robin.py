#!/usr/bin/env python3
import os
import shutil
import tempfile
import uuid
import yaml
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Optional


def _now():
    return datetime.now(timezone.utc).isoformat()


class MalformedSchedulerState(RuntimeError):
    pass


class RoundRobinScheduler:
    def __init__(self, state_file: Path, client: str = "", country: str = ""):
        self.state_file = Path(state_file)
        self.client, self.country = client, country
        self._init_state()
        if self.state_file.exists():
            self._load()

    def _init_state(self):
        self.state = {"schema_version": 2, "created_at": _now(), "updated_at": None, "cursor": 0, "tasks": []}

    def reset(self):
        self._init_state()
        self._save()

    def _load(self):
        try:
            data = yaml.safe_load(self.state_file.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("tasks", []), list):
                raise ValueError("state must be a mapping containing a tasks list")
            if any(not isinstance(task, dict) or not task.get("source_id") for task in data.get("tasks", [])):
                raise ValueError("every scheduler task must contain a source_id")
            self.state.update(data)
        except Exception as exc:
            backup = self.state_file.with_name(
                f"{self.state_file.name}.malformed-{datetime.now().strftime('%Y%m%d%H%M%S%f')}-{uuid.uuid4().hex}.bak"
            )
            shutil.copy2(self.state_file, backup)
            raise MalformedSchedulerState(f"Malformed scheduler state backed up to {backup}: {exc}") from exc

    def _save(self):
        self.state["updated_at"] = _now()
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f".{self.state_file.name}.", dir=self.state_file.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                yaml.safe_dump(self.state, f, sort_keys=False)
                f.flush(); os.fsync(f.fileno())
            os.replace(tmp, self.state_file)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)

    def _identity(self, task):
        return (task.get("client", self.client), task.get("country", self.country), task["source_id"])

    def bootstrap(self, tasks: List[Dict]):
        # Enrich legacy tasks in place so persisted identity becomes unambiguous.
        for task in self.state["tasks"]:
            task.setdefault("client", self.client)
            task.setdefault("country", self.country)
            task["active"] = False
        existing = {self._identity(t) for t in self.state["tasks"]}
        for item in sorted(tasks, key=lambda t: (t["source_id"], str(t.get("target_id", "")))):
            task = self._new_task(item["source_id"], item.get("target_id"))
            if self._identity(task) not in existing:
                self.state["tasks"].append(task); existing.add(self._identity(task))
            else:
                next(t for t in self.state["tasks"] if self._identity(t) == self._identity(task))["active"] = True
        self._save()
        return self.state

    def _new_task(self, source_id: str, target_id: Optional[str]):
        return {"client": self.client, "country": self.country, "source_id": source_id, "active": True,
                "target_id": target_id, "last_result": None, "last_reason": None,
                "last_run": None, "runs": 0, "retry_at": None}

    def next(self) -> Optional[Dict]:
        tasks = [task for task in self.state["tasks"] if task.get("active", True)]
        if not tasks: return None
        idx = self.state["cursor"] % len(tasks)
        self.state["cursor"] = (idx + 1) % len(tasks); self._save()
        return dict(tasks[idx])

    def update(self, task: Dict, result):
        result = result if isinstance(result, dict) else {"status": str(result)}
        for current in self.state["tasks"]:
            if self._identity(current) == self._identity(task):
                current.update(last_result=result["status"], last_reason=result.get("reason"),
                               last_run=_now(), runs=current.get("runs", 0) + 1,
                               retry_at=result.get("retry_at"))
                break
        self._save()

    def stats(self) -> Dict:
        return self.state

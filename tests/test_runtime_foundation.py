import contextlib
import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "Backend")]


def forbidden(*args, **kwargs):
    raise AssertionError("network or external subprocess access attempted")


class OfflineTestCase(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(mock.patch.object(socket.socket, "connect", forbidden))
        self.stack.enter_context(mock.patch("socket.create_connection", forbidden))
        self.stack.enter_context(mock.patch("urllib.request.urlopen", forbidden))
        self.stack.enter_context(mock.patch("http.client.HTTPConnection.request", forbidden))
        self.stack.enter_context(mock.patch("subprocess.run", forbidden))
        self.stack.enter_context(mock.patch("subprocess.Popen", forbidden))
        try:
            import requests
            self.stack.enter_context(mock.patch.object(requests.sessions.Session, "request", forbidden))
        except ImportError:
            pass
        self.temp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.data_root = Path(self.temp)
        self.stack.enter_context(mock.patch.dict(os.environ, {"METACRAWLER_DATA_ROOT": self.temp}))

    def tearDown(self):
        self.stack.close()


class RuntimeConfigurationTests(OfflineTestCase):
    def test_environment_override_and_missing_root(self):
        from config.runtime import RuntimeConfigError, get_data_root, validate_data_root
        self.assertEqual(get_data_root(), self.data_root.resolve())
        os.environ["METACRAWLER_DATA_ROOT"] = str(self.data_root / "missing")
        with self.assertRaisesRegex(RuntimeConfigError, "does not exist"):
            validate_data_root()

    def test_unwritable_root_fails_clearly(self):
        from config.runtime import RuntimeConfigError, validate_data_root
        with mock.patch("config.runtime.tempfile.mkstemp", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(RuntimeConfigError, "not writable"):
                validate_data_root()

    def test_validate_config_is_offline(self):
        import runner
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            runner.command(types.SimpleNamespace(command="validate-config"))
        self.assertIn("Configuration valid", output.getvalue())


class PlanTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.urls = ROOT / "clients/veredictum/ti-urls.txt"

    def _repo_snapshot(self):
        result = {}
        for path in ROOT.rglob("*"):
            if path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts:
                result[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        return result

    def test_plans_are_scoped_deterministic_atomic_and_repo_safe(self):
        from core.bootstrap_sources import bootstrap, plan_path
        before = self._repo_snapshot()
        a = Path(bootstrap("veredictum", "ti", str(self.urls)))
        first = a.read_bytes()
        self.assertEqual(first, Path(bootstrap("veredictum", "ti", str(self.urls))).read_bytes())
        b = Path(bootstrap("veredictum", "zz", str(self.urls)))
        self.assertNotEqual(a, b)
        self.assertTrue(a.match("*/veredictum/ti/_plans/sources.yaml"))
        self.assertFalse(list(a.parent.glob(".sources.*")))
        self.assertEqual(before, self._repo_snapshot())
        self.assertNotEqual(plan_path("one", "ti"), plan_path("two", "ti"))

    def test_plan_status_commands_are_offline_and_repo_safe(self):
        import runner
        before = self._repo_snapshot()
        with contextlib.redirect_stdout(io.StringIO()):
            runner.command(types.SimpleNamespace(command="plan", client="veredictum", country="ti"))
            runner.command(types.SimpleNamespace(command="status"))
        self.assertEqual(before, self._repo_snapshot())


class SchedulerTests(OfflineTestCase):
    def test_persistence_deterministic_merge_migration_and_removed_tasks(self):
        import yaml
        from core.utils.round_robin import RoundRobinScheduler
        path = self.data_root / "state.yaml"
        path.write_text(yaml.safe_dump({"cursor": 0, "tasks": [{"source_id": "old", "runs": 7,
                            "last_result": "downloaded"}]}), encoding="utf-8")
        rr = RoundRobinScheduler(path, "client", "ti")
        rr.bootstrap([{"source_id": "z"}, {"source_id": "old"}, {"source_id": "a"}])
        tasks = rr.state["tasks"]
        self.assertEqual(tasks[0]["runs"], 7)
        self.assertEqual((tasks[0]["client"], tasks[0]["country"]), ("client", "ti"))
        self.assertEqual([t["source_id"] for t in tasks[1:]], ["a", "z"])
        rr.bootstrap([{"source_id": "a"}])
        self.assertFalse(next(t for t in rr.state["tasks"] if t["source_id"] == "old")["active"])
        self.assertEqual(rr.next()["source_id"], "a")

    def test_identity_scope_and_atomic_replacement(self):
        from core.utils.round_robin import RoundRobinScheduler
        path = self.data_root / "state.yaml"
        rr = RoundRobinScheduler(path, "one", "ti")
        with mock.patch("core.utils.round_robin.os.replace", wraps=os.replace) as replace:
            rr.bootstrap([{"source_id": "same"}])
        replace.assert_called()
        self.assertFalse(list(self.data_root.glob(".state.yaml.*")))
        self.assertNotEqual(rr._identity({"source_id": "same", "client": "one", "country": "ti"}),
                            rr._identity({"source_id": "same", "client": "two", "country": "ti"}))

    def test_update_survives_reload_and_reset_is_explicit_and_scoped(self):
        from core.utils.round_robin import RoundRobinScheduler
        import runner
        path = self.data_root / "c" / "ti" / "_state" / "round_robin.yaml"
        rr = RoundRobinScheduler(path, "c", "ti"); rr.bootstrap([{"source_id": "a"}])
        rr.update(rr.next(), {"status": "downloaded", "reason": "new"})
        self.assertEqual(RoundRobinScheduler(path, "c", "ti").state["tasks"][0]["runs"], 1)
        with self.assertRaisesRegex(RuntimeError, "requires --yes"):
            runner.command(types.SimpleNamespace(command="reset-state", client="c", country="ti", yes=False))
        other = self.data_root / "other" / "ti" / "_state" / "round_robin.yaml"
        RoundRobinScheduler(other, "other", "ti").bootstrap([{"source_id": "x"}])
        runner.command(types.SimpleNamespace(command="reset-state", client="c", country="ti", yes=True))
        self.assertEqual(RoundRobinScheduler(path, "c", "ti").state["tasks"], [])
        self.assertEqual(len(RoundRobinScheduler(other, "other", "ti").state["tasks"]), 1)

    def test_malformed_state_has_unique_backups_and_is_reported(self):
        from core.utils.round_robin import MalformedSchedulerState, RoundRobinScheduler
        path = self.data_root / "bad.yaml"
        for _ in range(2):
            path.write_text("[bad", encoding="utf-8")
            with self.assertRaisesRegex(MalformedSchedulerState, "backed up"):
                RoundRobinScheduler(path)
        self.assertEqual(len(list(self.data_root.glob("bad.yaml.malformed-*.bak"))), 2)

    def test_bad_task_is_rejected_without_replacing_source(self):
        import yaml
        from core.utils.round_robin import MalformedSchedulerState, RoundRobinScheduler
        path = self.data_root / "bad-task.yaml"
        path.write_text(yaml.safe_dump({"tasks": [{"runs": 2}]}), encoding="utf-8")
        original = path.read_bytes()
        with self.assertRaises(MalformedSchedulerState): RoundRobinScheduler(path)
        self.assertEqual(path.read_bytes(), original)


class ResultAndLoggingTests(OfflineTestCase):
    def test_legacy_and_structured_results(self):
        from core.results import normalize_result
        for status in ("downloaded", "skipped", "failed"):
            self.assertEqual(normalize_result(status, "s").status, status)
        raw = {"status": "temporarily_blocked", "reason": "rate limited", "attempted_url": "u",
               "downloaded_path": "p", "content_hash": "h", "http_status": 429,
               "error_type": "HTTPError", "error_message": "blocked", "retryable": True,
               "retry_at": "later", "backoff_class": "long"}
        result = normalize_result(raw, "s")
        for key, value in raw.items(): self.assertEqual(getattr(result, key), value)

    def _manager(self):
        import core.crawler_manager as cm
        return cm, cm.CrawlerManager("veredictum", "ti")

    def test_human_and_valid_jsonl_logs(self):
        _, manager = self._manager()
        logs = self.data_root / "veredictum/ti/_logs"; logs.mkdir(parents=True)
        manager.log_file = logs / "run.log"; manager.jsonl_file = logs / "run.jsonl"
        manager.log("hello"); manager.event("event", source="s")
        self.assertIn("hello", manager.log_file.read_text())
        self.assertIsInstance(json.loads(manager.jsonl_file.read_text()), dict)

    def test_exception_and_legacy_skip_remain_distinct(self):
        cm, manager = self._manager(); manager.source_configs = {"s": {}}
        failing = types.SimpleNamespace(download_one=mock.Mock(side_effect=ValueError("boom")))
        skipped = types.SimpleNamespace(download_one=mock.Mock(return_value="skipped"))
        with mock.patch.object(cm, "load_crawler", return_value=failing): first = manager._run_task({"source_id": "s"})
        with mock.patch.object(cm, "load_crawler", return_value=skipped): second = manager._run_task({"source_id": "s"})
        self.assertEqual((first.status, first.error_type), ("failed", "ValueError"))
        self.assertEqual((second.status, second.reason), ("skipped", "legacy_result:skipped"))


class CompatibilityAndManagerTests(OfflineTestCase):
    def test_discovery_loader_and_interactive_entrypoint(self):
        import runner
        self.assertIn("veredictum", runner.list_clients())
        self.assertIn("ti-urls.txt", runner.list_url_files("veredictum"))
        self.assertIn("asamblea", runner.list_crawlers("veredictum", "ti"))
        import core.crawler_loader as loader
        sentinel = types.ModuleType("asamblea")
        with mock.patch.object(loader.importlib, "import_module", return_value=sentinel) as importer:
            self.assertIs(loader.load_crawler("veredictum", "ti", "asamblea"), sentinel)
        importer.assert_called_once_with("clients.veredictum.crawlers.ti.asamblea")
        self.assertTrue(callable(runner.run))

    def test_manager_preserves_state_and_runs_once_per_selected_source(self):
        import core.crawler_manager as cm
        from core.utils.round_robin import RoundRobinScheduler
        state = self.data_root / "veredictum/ti/_state/round_robin.yaml"
        rr = RoundRobinScheduler(state, "veredictum", "ti"); rr.bootstrap([{"source_id": "a"}])
        rr.update(rr.next(), {"status": "skipped", "reason": "prior"})
        manager = cm.CrawlerManager("veredictum", "ti")
        manager.sources_override = [{"id": "a", "base_urls": ["https://invalid/a"]},
                                    {"id": "b", "base_urls": ["https://invalid/b"]}]
        manager.select_mode_interactively = lambda: "incremental"
        calls = []
        def fake(task):
            from core.results import CrawlerResult
            calls.append(task["source_id"]); return CrawlerResult("skipped", "test", task["source_id"])
        manager._run_task = fake
        with contextlib.redirect_stdout(io.StringIO()): manager.run()
        self.assertEqual(sorted(calls), ["a", "b"])
        loaded = RoundRobinScheduler(state, "veredictum", "ti")
        self.assertEqual(next(t for t in loaded.state["tasks"] if t["source_id"] == "a")["runs"], 2)


if __name__ == "__main__":
    unittest.main()

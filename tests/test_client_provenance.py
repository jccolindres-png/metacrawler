"""Offline checks for client isolation and exact download provenance."""

import ast
import contextlib
import hashlib
import io
import json
import os
import socket
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "Backend")]

from core.source_sidecar import save_download, sidecar_path, write_sidecar


def forbidden(*_args, **_kwargs):
    raise AssertionError("real network request attempted")


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = mock.patch.dict(os.environ, {"METACRAWLER_DATA_ROOT": self.temp.name})
        env.start()
        self.addCleanup(env.stop)
        for target, name in ((socket.socket, "connect"), (socket, "create_connection")):
            patcher = mock.patch.object(target, name, forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)
        import requests
        network = mock.patch.object(requests.sessions.Session, "request", forbidden)
        network.start()
        self.addCleanup(network.stop)
        self.root = Path(self.temp.name)

    def test_new_client_reuses_modules_and_keeps_state_separate(self):
        import runner
        from core.bootstrap_sources import bootstrap
        from core.crawler_loader import load_crawler
        from core.crawler_manager import CrawlerManager
        from clients.veredictum.classifier import Classifier

        old_state = self.root / "veredictum/ti/_state/round_robin.yaml"
        old_state.parent.mkdir(parents=True)
        old_state.write_bytes(b"historical scheduler bytes\n")
        old_document = self.root / "veredictum/ti/asamblea/existing.pdf"
        old_document.parent.mkdir(parents=True)
        old_document.write_bytes(b"historical document bytes")

        self.assertIn("costa_rica", runner.list_clients())
        self.assertIn("ti-urls.txt", runner.list_url_files("costa_rica"))
        self.assertIn("asamblea", runner.list_crawlers("costa_rica", "ti"))
        self.assertIn("pgr", runner.list_crawlers("costa_rica", "ti"))
        self.assertIn("sinalevi", runner.list_crawlers("costa_rica", "ti"))
        self.assertIs(load_crawler("costa_rica", "ti", "asamblea"),
                      load_crawler("veredictum", "ti", "asamblea"))
        for crawler in ("pgr", "sinalevi"):
            self.assertIs(load_crawler("costa_rica", "ti", crawler),
                          load_crawler("veredictum", "ti", crawler))
        self.assertEqual(Classifier().classify("https://sinalevi.go.cr/")["source_id"], "sinalevi")
        self.assertEqual(Classifier().classify("https://www.pgrweb.go.cr/scij/")["source_id"], "sinalevi")
        self.assertEqual(Classifier().classify("https://www.pgr.go.cr/")["source_id"], "pgr")

        with contextlib.redirect_stdout(io.StringIO()):
            plan = Path(bootstrap("costa_rica", "ti", str(ROOT / "clients/costa_rica/ti-urls.txt")))
            manager = CrawlerManager("costa_rica", "ti", plan_path=plan)
        sources = manager.load_sources()
        self.assertTrue(next(source for source in sources if source["id"] == "asamblea")["targets"])
        self.assertEqual(
            next(source for source in sources if source["id"] == "sinalevi")["targets"],
            [{"url": "https://sinalevi.go.cr/"}],
        )
        manager.rr.bootstrap([{"source_id": "asamblea"}])
        self.assertTrue((self.root / "costa_rica/ti/_state/round_robin.yaml").exists())
        self.assertEqual(old_state.read_bytes(), b"historical scheduler bytes\n")
        self.assertEqual(old_document.read_bytes(), b"historical document bytes")
        self.assertFalse((self.root / "costa_rica/ti/asamblea").exists())
        manager.source_configs = {source["id"]: source for source in sources}
        contexts = []
        stub = mock.Mock()
        stub.download_one.side_effect = lambda context: contexts.append(context) or "skipped"
        with mock.patch("core.crawler_manager.load_crawler", return_value=stub):
            with contextlib.redirect_stdout(io.StringIO()):
                for source_id in ("pgr", "sinalevi"):
                    manager._run_task({"source_id": source_id})
        for source_id, context in zip(("pgr", "sinalevi"), contexts):
            self.assertEqual(Path(context["state_file"]),
                             self.root / "costa_rica/ti/_state" / f"{source_id}.json")
            self.assertEqual(Path(context["download_dir"]),
                             self.root / "costa_rica/ti" / source_id)
            self.assertFalse((self.root / "veredictum/ti/_state" / f"{source_id}.json").exists())

    def test_sidecar_uses_exact_bytes_and_preserves_existing_file(self):
        document = self.root / "new.pdf"
        payload = b"%PDF-1.4 original bytes %%EOF"
        final_url = "https://files.example.org/final/document.pdf"
        self.assertTrue(save_download(payload, document, final_url))
        metadata = json.loads(sidecar_path(document).read_text(encoding="utf-8"))
        self.assertEqual(metadata["source_url"], final_url)
        self.assertEqual(metadata["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(metadata["size_bytes"], len(payload))
        self.assertEqual(datetime.fromisoformat(metadata["downloaded_at_utc"]).utcoffset(),
                         timezone.utc.utcoffset(None))
        original_sidecar = sidecar_path(document).read_bytes()
        self.assertFalse(save_download(b"changed", document, final_url))
        self.assertEqual(document.read_bytes(), payload)
        self.assertEqual(sidecar_path(document).read_bytes(), original_sidecar)
        self.assertEqual(write_sidecar(document, payload, "https://files.example.org/another.pdf"),
                         sidecar_path(document))
        self.assertEqual(sidecar_path(document).read_bytes(), original_sidecar)

    def test_missing_final_url_and_sidecar_failure_never_count_as_saved(self):
        document = self.root / "new.pdf"
        with self.assertRaisesRegex(ValueError, "final response URL"):
            save_download(b"%PDF", document, None)
        self.assertFalse(document.exists())
        with mock.patch("core.source_sidecar.write_sidecar", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                save_download(b"%PDF", document, "https://files.example.org/final.pdf")
        self.assertFalse(document.exists())
        self.assertFalse(sidecar_path(document).exists())

    def test_discovery_crawler_records_response_final_url(self):
        from clients.veredictum.crawlers.ti import ucr_kerwa

        class Response:
            def __init__(self, content, url, content_type="text/html"):
                self.content = content
                self.text = content.decode("utf-8", errors="ignore")
                self.url = url
                self.status_code = 200
                self.headers = {"Content-Type": content_type}

        class Session:
            def __init__(self):
                self.responses = iter([
                    Response(b'<a href="doc.pdf">PDF</a>', "https://www.kerwa.ucr.ac.cr/list"),
                    Response(b"%PDF-1.4 exact bytes %%EOF", "https://www.kerwa.ucr.ac.cr/final/doc.pdf",
                             "application/pdf"),
                ])

            def get(self, *_args, **_kwargs):
                return next(self.responses)

        source = {"base_urls": ["https://www.kerwa.ucr.ac.cr/list"],
                  "download_dir": str(self.root / "costa_rica/ti/ucr_kerwa"),
                  "state_file": str(self.root / "costa_rica/ti/_state/ucr_kerwa.json"),
                  "mode": "incremental"}
        Path(source["state_file"]).parent.mkdir(parents=True)
        with mock.patch.object(ucr_kerwa.requests, "Session", return_value=Session()):
            self.assertEqual(ucr_kerwa.download_one(source), "downloaded")
        documents = list(Path(source["download_dir"]).glob("*.pdf"))
        self.assertEqual(len(documents), 1)
        metadata = json.loads(sidecar_path(documents[0]).read_text(encoding="utf-8"))
        self.assertEqual(metadata["source_url"], "https://www.kerwa.ucr.ac.cr/final/doc.pdf")
        self.assertEqual(metadata["sha256"], hashlib.sha256(documents[0].read_bytes()).hexdigest())
        original, sidecar = documents[0].read_bytes(), sidecar_path(documents[0]).read_bytes()
        source["mode"] = "full"
        second = Session()
        second.responses = iter([Response(b'<a href="doc.pdf">PDF</a>', "https://www.kerwa.ucr.ac.cr/list")])
        with mock.patch.object(ucr_kerwa.requests, "Session", return_value=second):
            self.assertEqual(ucr_kerwa.download_one(source), "skipped")
        self.assertEqual(documents[0].read_bytes(), original)
        self.assertEqual(sidecar_path(documents[0]).read_bytes(), sidecar)

    def test_all_discovery_writes_use_provenance_helper(self):
        paths = [ROOT / "Backend/core/base_crawler.py", *
                 (ROOT / "clients/veredictum/crawlers/ti").glob("*.py")]
        for path in paths:
            if path.name == "__init__.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
            self.assertFalse(any(isinstance(node.func, ast.Attribute) and node.func.attr == "write_bytes"
                                 for node in calls), path.name)
            self.assertTrue(any(isinstance(node.func, ast.Name) and node.func.id == "save_download"
                                for node in calls), path.name)


if __name__ == "__main__":
    unittest.main()

"""Offline content-deduplication and publication regression tests."""

import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "Backend")]

from core.source_sidecar import save_download, sidecar_path
from core.crawler_manager import CrawlerManager
from clients.veredictum.crawlers.ti import pgr, sinalevi, tramites, ucr_kerwa


PDF_A = b"%PDF-1.4\nfirst document\n%%EOF"
PDF_B = b"%PDF-1.4\nsecond document\n%%EOF"
URL_A = "https://example.test/first.pdf"
URL_B = "https://example.test/second.pdf"


class Response:
    def __init__(self, url, body, content_type="application/pdf"):
        self.url = url
        self.content = body
        self.status_code = 200
        self.headers = {"Content-Type": content_type}
        self.text = body.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.content)


class ContentDedupeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.guard = mock.patch.object(requests.sessions.Session, "request",
                                       side_effect=AssertionError("network request attempted"))
        self.guard.start()
        self.addCleanup(self.guard.stop)

    def acquire(self, data, source, name="document.pdf", url=URL_A):
        dest = source / name
        return save_download(data, dest, url, source_root=source, return_outcome=True)

    def test_new_document_and_sidecar_preserve_exact_provenance(self):
        source = self.root / "client/ti/source"
        outcome = self.acquire(PDF_A, source)
        self.assertEqual(outcome.status, "downloaded")
        self.assertEqual(outcome.path.read_bytes(), PDF_A)
        self.assertEqual(outcome.content_hash, hashlib.sha256(PDF_A).hexdigest())
        provenance = json.loads(sidecar_path(outcome.path).read_text())
        self.assertEqual(provenance["source_url"], URL_A)
        self.assertEqual(provenance["sha256"], outcome.content_hash)
        self.assertEqual(provenance["size_bytes"], len(PDF_A))
        self.assertIn("downloaded_at_utc", provenance)
        index = json.loads((source / ".dedupe_store.json").read_text())
        self.assertEqual(index["hashes"][outcome.content_hash]["path"], "document.pdf")
        self.assertFalse(list(source.rglob(".source-*")))
        self.assertFalse(list(source.rglob(".dedupe-*")))

    def test_same_content_different_urls_names_and_restart(self):
        source = self.root / "client/ti/source"
        first = self.acquire(PDF_A, source)
        original_sidecar = sidecar_path(first.path).read_bytes()
        repeated = self.acquire(PDF_A, source)
        renamed = self.acquire(PDF_A, source, "another.pdf", URL_B)
        self.assertEqual((repeated.status, renamed.status), ("duplicate", "duplicate"))
        self.assertEqual(renamed.path, first.path)
        self.assertEqual(list(source.glob("*.pdf")), [first.path])
        self.assertEqual(sidecar_path(first.path).read_bytes(), original_sidecar)
        # A fresh call reads persisted files; no process-local cache is needed.
        self.assertEqual(self.acquire(PDF_A, source, "restart.pdf").status, "duplicate")

    def test_source_client_and_country_isolation(self):
        roots = (self.root / "client-a/ti/source-1", self.root / "client-a/ti/source-2",
                 self.root / "client-b/ti/source-1", self.root / "client-a/other/source-1")
        for source in roots:
            outcome = self.acquire(PDF_A, source)
            self.assertEqual(outcome.status, "downloaded")
            self.assertEqual(outcome.path.read_bytes(), PDF_A)
            self.assertTrue(sidecar_path(outcome.path).exists())
        self.assertEqual(len(list(self.root.rglob("document.pdf"))), 4)

    def test_same_filename_different_content_gets_new_name(self):
        source = self.root / "client/ti/source"
        first = self.acquire(PDF_A, source)
        original_sidecar = sidecar_path(first.path).read_bytes()
        second = self.acquire(PDF_B, source, url=URL_B)
        self.assertEqual(second.status, "downloaded")
        self.assertNotEqual(second.path, first.path)
        self.assertEqual(second.path.read_bytes(), PDF_B)
        self.assertEqual(first.path.read_bytes(), PDF_A)
        self.assertEqual(sidecar_path(first.path).read_bytes(), original_sidecar)
        self.assertEqual(json.loads(sidecar_path(second.path).read_text())["source_url"], URL_B)
        self.assertEqual(self.acquire(PDF_B, source, url=URL_B).status, "duplicate")

    def test_historical_document_without_sidecar_is_not_rewritten(self):
        source = self.root / "client/ti/source"
        source.mkdir(parents=True)
        historic = source / "historic.pdf"
        historic.write_bytes(PDF_A)
        before = historic.stat().st_mtime_ns
        outcome = self.acquire(PDF_A, source, "new.pdf", URL_B)
        self.assertEqual(outcome.status, "duplicate")
        self.assertEqual(outcome.path, historic)
        self.assertEqual(historic.stat().st_mtime_ns, before)
        self.assertFalse(sidecar_path(historic).exists())

    def test_failed_stage_sidecar_and_index_leave_no_acquisition(self):
        from core import source_sidecar
        from core.utils import dedupe
        source = self.root / "client/ti/source"
        for target, attribute in ((source_sidecar, "_stage"),
                                  (source_sidecar, "write_sidecar"),
                                  (source_sidecar, "_sync_directory"), (dedupe, "_record")):
            with self.subTest(attribute=attribute):
                with mock.patch.object(target, attribute, side_effect=OSError("disk full")):
                    with self.assertRaisesRegex(OSError, "disk full"):
                        self.acquire(PDF_A, source)
                self.assertEqual(list(source.rglob("*.pdf")), [])
                self.assertEqual(list(source.rglob("*.source.json")), [])
                self.assertFalse((source / ".dedupe_store.json").exists())
                self.assertFalse(list(source.rglob(".source-*")))
                self.assertFalse(list(source.rglob(".dedupe-*")))
        self.assertEqual(self.acquire(PDF_A, source).status, "downloaded")

    def test_restart_recovers_published_file_missing_index(self):
        source = self.root / "client/ti/source"
        first = self.acquire(PDF_A, source)
        (source / ".dedupe_store.json").unlink()
        duplicate = self.acquire(PDF_A, source, "other.pdf", URL_B)
        self.assertEqual(duplicate.status, "duplicate")
        self.assertEqual(duplicate.path, first.path)
        self.assertEqual(len(list(source.glob("*.pdf"))), 1)

    def test_tramites_cursor_and_manager_distinguish_duplicate(self):
        import core.crawler_manager as manager_module
        with mock.patch.dict(os.environ, {"METACRAWLER_DATA_ROOT": str(self.root)}):
            with contextlib.redirect_stdout(io.StringIO()):
                manager = CrawlerManager("client", "ti")
        manager.source_configs = {"tramites": {"base_urls": ["https://example.test"]}}
        log_dir = manager.root_dir / "_logs"
        log_dir.mkdir(parents=True)
        manager.jsonl_file = log_dir / "events.jsonl"
        url = "https://example.test/pub/tramites/MINAE/manual-2025-v2.pdf"
        response = Response(url, PDF_A)
        session = types.SimpleNamespace(get=lambda requested, **kwargs: response)
        with mock.patch.object(manager_module, "load_crawler", return_value=tramites), \
             mock.patch.object(tramites.requests, "Session", return_value=session):
            with contextlib.redirect_stdout(io.StringIO()):
                first = manager._run_task({"source_id": "tramites"})
            cursor = manager.state_dir / "tramites.json"
            self.assertEqual(cursor.read_text(), "1")
            cursor.write_text("0")
            with contextlib.redirect_stdout(io.StringIO()):
                second = manager._run_task({"source_id": "tramites"})
        self.assertEqual((first.status, second.status), ("downloaded", "duplicate"))
        self.assertEqual(cursor.read_text(), "1")
        self.assertEqual(manager.stats, {"attempted": 2, "downloaded": 1, "failed": 0, "skipped": 1})
        events = [json.loads(line) for line in manager.jsonl_file.read_text().splitlines()]
        self.assertEqual([event["result_status"] for event in events], ["downloaded", "duplicate"])
        self.assertEqual(events[1]["content_hash"], hashlib.sha256(PDF_A).hexdigest())

    def test_repository_rechecks_same_url_and_preserves_both_versions(self):
        page_url = "https://example.test/repository"
        pdf_url = "https://example.test/document.pdf"
        page = Response(page_url, f'<a href="{pdf_url}">PDF</a>'.encode(), "text/html")
        payload = [PDF_A]
        session = types.SimpleNamespace(get=lambda url, **kwargs: page if url == page_url
                                        else Response(pdf_url, payload[0]))
        source = {"download_dir": str(self.root / "client/ti/ucr_kerwa"),
                  "state_file": str(self.root / "client/ti/_state/ucr_kerwa.json"),
                  "base_urls": [page_url]}
        Path(source["state_file"]).parent.mkdir(parents=True)
        with mock.patch.object(ucr_kerwa.requests, "Session", return_value=session):
            first = ucr_kerwa.download_one(source)
            payload[0] = PDF_B
            second = ucr_kerwa.download_one(source)
            third = ucr_kerwa.download_one(source)
        self.assertEqual((first, second), ("downloaded", "downloaded"))
        self.assertEqual(third.status, "duplicate")
        self.assertEqual({path.read_bytes() for path in Path(source["download_dir"]).glob("*.pdf")},
                         {PDF_A, PDF_B})
        self.assertEqual(Path(source["state_file"]).read_text(), "done")

    def test_pgr_same_bytes_at_two_urls_advances_as_duplicate(self):
        base = "https://www.pgr.go.cr"
        archive = pgr.ARCHIVE_URL
        post1, post2 = base + "/post-one/", base + "/post-two/"
        pdf1, pdf2 = base + "/first.pdf", base + "/second.pdf"
        routes = {
            archive: Response(archive, (
                f'<article class="post"><h2><a href="{post1}">One</a></h2></article>'
                f'<article class="post"><h2><a href="{post2}">Two</a></h2></article>'
            ).encode(), "text/html"),
            post1: Response(post1, f'<main><a href="{pdf1}">PDF</a></main>'.encode(), "text/html"),
            post2: Response(post2, f'<main><a href="{pdf2}">PDF</a></main>'.encode(), "text/html"),
            pdf1: Response(pdf1, PDF_A), pdf2: Response(pdf2, PDF_A),
        }
        session = types.SimpleNamespace(get=lambda url, **kwargs: routes[url])
        source = {"download_dir": str(self.root / "client/ti/pgr"),
                  "state_file": str(self.root / "client/ti/_state/pgr.json")}
        with mock.patch.object(pgr.requests, "Session", return_value=session):
            first = pgr.download_one(source)
            second = pgr.download_one(source)
        self.assertEqual(first, "downloaded")
        self.assertEqual(second.status, "duplicate")
        self.assertEqual(len(list(Path(source["download_dir"]).glob("*.pdf"))), 1)
        state = json.loads(Path(source["state_file"]).read_text())
        self.assertEqual((state["post_index"], state["pdf_index"]), (1, 1))

    def test_sinalevi_checks_content_before_advancing_identity(self):
        if not hasattr(sinalevi, "SEARCH_URL"):
            self.skipTest("official SINALEVI rewrite is outside the committed Block 3 scope")
        record = [{"IdFichaNorma": 7, "IdVersionNorma": 9}]
        routes = {
            ("GET", sinalevi.SEARCH_URL): Response(sinalevi.SEARCH_URL, json.dumps(record).encode()),
            ("GET", sinalevi.DETAIL_URL): Response(sinalevi.DETAIL_URL,
                b'<input id="idFichaNorma" value="7"><input id="versionNorma" value="9">'
                b'<div id="contenidoPDF"><div id="divVista"></div></div>', "text/html"),
            ("POST", sinalevi.TEXT_URL): Response(sinalevi.TEXT_URL,
                b'{"html":"<div id=\\"contenedorTexto\\">Text</div>"}', "application/json"),
            ("POST", sinalevi.PDF_URL): Response(sinalevi.PDF_URL, PDF_A),
        }
        session = types.SimpleNamespace(
            get=lambda url, **kwargs: routes[("GET", url)],
            post=lambda url, **kwargs: routes[("POST", url)])
        source = {"download_dir": str(self.root / "client/ti/sinalevi"),
                  "state_file": str(self.root / "client/ti/_state/sinalevi.json")}
        with mock.patch.object(sinalevi.requests, "Session", return_value=session):
            first = sinalevi.download_one(source)
            Path(source["state_file"]).write_text("{}")
            second = sinalevi.download_one(source)
        self.assertEqual(first, "downloaded")
        self.assertEqual(second.status, "duplicate")
        self.assertEqual(json.loads(Path(source["state_file"]).read_text())["query_index"], 1)
        self.assertEqual(len(list(Path(source["download_dir"]).glob("*.pdf"))), 1)

    def test_sinalevi_legacy_route_checks_bytes_before_advancing(self):
        if not hasattr(sinalevi, "BASE_URL"):
            self.skipTest("legacy route is absent from the current working tree")
        page_url = sinalevi.BASE_URL.format(1)
        pdf_url = "https://example.test/sinalevi.pdf"
        page = Response(page_url, f'<a href="{pdf_url}">PDF</a>'.encode(), "text/html")
        pdf = Response(pdf_url, PDF_A)
        routes = {page_url: page, pdf_url: pdf}
        source = {"download_dir": str(self.root / "client/ti/sinalevi"),
                  "state_file": str(self.root / "client/ti/_state/sinalevi.json")}
        Path(source["state_file"]).parent.mkdir(parents=True)
        with mock.patch.object(sinalevi.requests, "get", side_effect=lambda url, **kwargs: routes[url]):
            first = sinalevi.download_one(source)
            Path(source["state_file"]).write_text("0")
            second = sinalevi.download_one(source)
        self.assertEqual(first, "downloaded")
        self.assertEqual(second.status, "duplicate")
        self.assertEqual(Path(source["state_file"]).read_text(), "1")
        self.assertEqual(len(list(Path(source["download_dir"]).glob("*.pdf"))), 1)


if __name__ == "__main__":
    unittest.main()

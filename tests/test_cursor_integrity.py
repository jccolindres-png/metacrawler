"""Offline cursor and failure regression tests for specialized crawlers."""

import contextlib
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

from clients.veredictum.crawlers.ti import (
    asamblea, conare_kimuk, gaceta, instituciones_legacy,
    poder_judicial, tramites, ucr_kerwa, una_repositorio,
)
from core.crawler_manager import CrawlerManager
from core.results import CrawlerResult


PDF = b"%PDF-1.4\nfixture\n%%EOF"
BASE = "https://example.test"


class Response:
    def __init__(self, url, content, status=200, content_type="text/html"):
        self.url = url
        self.content = content
        self.status_code = status
        self.headers = {"Content-Type": content_type}
        self.text = content.decode("utf-8", errors="replace")


class Session:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        result = self.routes.get(url)
        if result is None:
            raise AssertionError(f"unmocked URL {url}")
        if isinstance(result, Exception):
            raise result
        return result


class CursorIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(mock.patch.dict(os.environ, {"METACRAWLER_DATA_ROOT": str(self.root)}))
        self.stack.enter_context(mock.patch.object(
            requests.sessions.Session, "request",
            side_effect=AssertionError("external network request attempted")))
        self.counter = 0

    def source(self, module, initial="seed"):
        self.counter += 1
        root = self.root / f"{module.__name__.split('.')[-1]}-{self.counter}"
        root.mkdir()
        state = root / "state.json"
        if initial is not None:
            state.write_text(initial)
        return {"download_dir": str(root / "docs"), "state_file": str(state),
                "base_urls": [BASE], "targets": [{"url": BASE}], "mode": "incremental"}

    def run_session(self, module, source, routes, save_error=None):
        session = Session(routes)
        request_patch = (mock.patch.object(module.requests, "get", side_effect=session.get)
                         if module is poder_judicial else
                         mock.patch.object(module.requests, "Session", return_value=session))
        with request_patch:
            if save_error is None:
                result = module.download_one(source)
            else:
                with mock.patch.object(module, "save_download", side_effect=save_error):
                    result = module.download_one(source)
        return result, session.calls

    def assert_retained(self, source, original):
        self.assertEqual(Path(source["state_file"]).read_text(), original)
        self.assertEqual(list(Path(source["download_dir"]).rglob("*.pdf")), [])

    def test_gaceta_failure_matrix_retries_same_date_then_downloads_once(self):
        page = BASE + "/cgi-bin/search.pl?query=&fecha=2026-10-28"
        pdf1, pdf2 = BASE + "/one.pdf", BASE + "/two.pdf"
        html = f'<a href="{pdf1}">one</a><a href="{pdf2}">two</a>'.encode()
        good = {page: Response(page, html), pdf1: Response(pdf1, PDF, content_type="application/pdf"),
                pdf2: Response(pdf2, PDF, content_type="application/pdf")}
        cases = (
            ("page_http", {**good, page: Response(page, b"bad", 503)}, None, "failed", 503),
            ("page_timeout", {**good, page: requests.Timeout("offline")}, None, "failed", None),
            ("page_empty", {**good, page: Response(page, b"")}, None, "site_changed", 200),
            ("pdf_http", {**good, pdf1: Response(pdf1, b"bad", 503)}, None, "failed", 503),
            ("pdf_timeout", {**good, pdf1: requests.Timeout("offline")}, None, "failed", None),
            ("pdf_invalid", {**good, pdf1: Response(pdf1, b"not a PDF")}, None, "invalid_document", 200),
            ("disk", good, PermissionError("read only"), "failed", None),
        )
        for label, routes, save_error, status, http_status in cases:
            with self.subTest(label=label):
                source = self.source(gaceta, "2026-10-27")
                result, calls = self.run_session(gaceta, source, routes, save_error)
                self.assertEqual(result.status, status)
                self.assertEqual(result.http_status, http_status)
                self.assert_retained(source, "2026-10-27")
                recovered, calls = self.run_session(gaceta, source, good)
                self.assertEqual(recovered, "downloaded")
                self.assertEqual(Path(source["state_file"]).read_text(), "2026-10-28")
                self.assertEqual(calls, [page, pdf1])
                self.assertEqual(len(list(Path(source["download_dir"]).glob("*.pdf"))), 1)

    def test_gaceta_verified_empty_and_matching_duplicate_advance(self):
        page = BASE + "/cgi-bin/search.pl?query=&fecha=2026-10-28"
        pdf = BASE + "/one.pdf"
        source = self.source(gaceta, "2026-10-27")
        empty, _ = self.run_session(gaceta, source, {page: Response(page, b"<html>No PDFs today</html>")})
        self.assertEqual(empty.status, "no_new_documents")
        self.assertEqual(Path(source["state_file"]).read_text(), "2026-10-28")
        Path(source["state_file"]).write_text("2026-10-27")
        routes = {page: Response(page, f'<a href="{pdf}">PDF</a>'.encode()),
                  pdf: Response(pdf, PDF, content_type="application/pdf")}
        self.assertEqual(self.run_session(gaceta, source, routes)[0], "downloaded")
        Path(source["state_file"]).write_text("2026-10-27")
        duplicate, _ = self.run_session(gaceta, source, routes)
        self.assertEqual(duplicate.status, "duplicate")
        self.assertEqual(Path(source["state_file"]).read_text(), "2026-10-28")

    def test_tramites_failure_matrix_retries_same_pattern_then_advances(self):
        url = BASE + "/pub/tramites/MINAE/manual-2025-v2.pdf"
        good = {url: Response(url, PDF, content_type="application/pdf")}
        cases = (
            ("http", {url: Response(url, b"missing", 503)}, None, "failed", 503),
            ("timeout", {url: requests.Timeout("offline")}, None, "failed", None),
            ("invalid", {url: Response(url, b"<html>error</html>")}, None, "invalid_document", 200),
            ("disk", good, PermissionError("read only"), "failed", None),
        )
        for label, routes, save_error, status, http_status in cases:
            with self.subTest(label=label):
                source = self.source(tramites, "0")
                result, _ = self.run_session(tramites, source, routes, save_error)
                self.assertEqual((result.status, result.http_status), (status, http_status))
                self.assert_retained(source, "0")
                recovered, calls = self.run_session(tramites, source, good)
                self.assertEqual(recovered, "downloaded")
                self.assertEqual(calls, [url])
                self.assertEqual(Path(source["state_file"]).read_text(), "1")
                self.assertEqual(len(list(Path(source["download_dir"]).glob("*.pdf"))), 1)

    def test_tramites_duplicate_exhaustion_and_malformed_state(self):
        url = BASE + "/pub/tramites/MINAE/manual-2025-v2.pdf"
        source = self.source(tramites, "0")
        routes = {url: Response(url, PDF, content_type="application/pdf")}
        self.assertEqual(self.run_session(tramites, source, routes)[0], "downloaded")
        Path(source["state_file"]).write_text("0")
        duplicate, _ = self.run_session(tramites, source, routes)
        self.assertEqual(duplicate.status, "duplicate")
        self.assertEqual(Path(source["state_file"]).read_text(), "1")
        Path(source["state_file"]).write_text("7")
        exhausted, calls = self.run_session(tramites, source, {})
        self.assertEqual(exhausted.status, "exhausted")
        self.assertEqual(calls, [])
        self.assertEqual(Path(source["state_file"]).read_text(), "7")
        Path(source["state_file"]).write_text("broken")
        invalid, calls = self.run_session(tramites, source, {})
        self.assertEqual(invalid.status, "manual_review")
        self.assertEqual(calls, [])
        self.assertEqual(Path(source["state_file"]).read_text(), "broken")

    def test_poder_judicial_failure_matrix_retries_same_id_then_downloads_once(self):
        page = BASE + "/BusquedaAPI/DetalleFallo?fallo=1"
        pdf = BASE + "/fallo.pdf"
        good = {page: Response(page, f'<a href="{pdf}">PDF</a>'.encode()),
                pdf: Response(pdf, PDF, content_type="application/pdf")}
        cases = (
            ("page_http", {**good, page: Response(page, b"bad", 503)}, None, "failed", 503),
            ("page_timeout", {**good, page: requests.Timeout("offline")}, None, "failed", None),
            ("page_empty", {**good, page: Response(page, b"")}, None, "site_changed", 200),
            ("missing_link", {**good, page: Response(page, b"<html>unexpected</html>")}, None, "site_changed", 200),
            ("pdf_http", {**good, pdf: Response(pdf, b"bad", 503)}, None, "failed", 503),
            ("pdf_timeout", {**good, pdf: requests.Timeout("offline")}, None, "failed", None),
            ("pdf_invalid", {**good, pdf: Response(pdf, b"bad")}, None, "invalid_document", 200),
            ("disk", good, PermissionError("read only"), "failed", None),
        )
        for label, routes, save_error, status, http_status in cases:
            with self.subTest(label=label):
                source = self.source(poder_judicial, "0")
                result, _ = self.run_session(poder_judicial, source, routes, save_error)
                self.assertEqual((result.status, result.http_status), (status, http_status))
                self.assert_retained(source, "0")
                recovered, calls = self.run_session(poder_judicial, source, good)
                self.assertEqual(recovered, "downloaded")
                self.assertEqual(calls, [page, pdf])
                self.assertEqual(Path(source["state_file"]).read_text(), "1")
                self.assertEqual(len(list(Path(source["download_dir"]).glob("*.pdf"))), 1)

    def test_poder_judicial_matching_duplicate_advances(self):
        page = BASE + "/BusquedaAPI/DetalleFallo?fallo=1"
        pdf = BASE + "/fallo.pdf"
        routes = {page: Response(page, f'<a href="{pdf}">PDF</a>'.encode()),
                  pdf: Response(pdf, PDF, content_type="application/pdf")}
        source = self.source(poder_judicial, "0")
        self.assertEqual(self.run_session(poder_judicial, source, routes)[0], "downloaded")
        Path(source["state_file"]).write_text("0")
        duplicate, _ = self.run_session(poder_judicial, source, routes)
        self.assertEqual(duplicate.status, "duplicate")
        self.assertEqual(Path(source["state_file"]).read_text(), "1")

    def test_state_write_failure_keeps_cursor_and_restart_recognizes_saved_file(self):
        page = BASE + "/cgi-bin/search.pl?query=&fecha=2026-10-28"
        gaceta_pdf = BASE + "/one.pdf"
        tramites_pdf = BASE + "/pub/tramites/MINAE/manual-2025-v2.pdf"
        fallo_page = BASE + "/BusquedaAPI/DetalleFallo?fallo=1"
        fallo_pdf = BASE + "/fallo.pdf"
        cases = (
            (gaceta, "2026-10-27", "2026-10-28", {
                page: Response(page, f'<a href="{gaceta_pdf}">PDF</a>'.encode()),
                gaceta_pdf: Response(gaceta_pdf, PDF, content_type="application/pdf")}),
            (tramites, "0", "1", {
                tramites_pdf: Response(tramites_pdf, PDF, content_type="application/pdf")}),
            (poder_judicial, "0", "1", {
                fallo_page: Response(fallo_page, f'<a href="{fallo_pdf}">PDF</a>'.encode()),
                fallo_pdf: Response(fallo_pdf, PDF, content_type="application/pdf")}),
        )
        original_write = Path.write_text
        for module, before, after, routes in cases:
            with self.subTest(module=module.__name__):
                source = self.source(module, before)
                state_path = Path(source["state_file"])

                def fail_state(path, *args, **kwargs):
                    if path == state_path:
                        raise PermissionError("state read only")
                    return original_write(path, *args, **kwargs)

                with mock.patch.object(Path, "write_text", fail_state):
                    with self.assertRaisesRegex(PermissionError, "state read only"):
                        self.run_session(module, source, routes)
                self.assertEqual(state_path.read_text(), before)
                self.assertEqual(len(list(Path(source["download_dir"]).rglob("*.pdf"))), 1)
                duplicate, _ = self.run_session(module, source, routes)
                self.assertEqual(duplicate.status, "duplicate")
                self.assertEqual(state_path.read_text(), after)

    def test_existing_different_bytes_publish_new_name_before_advancing(self):
        page = BASE + "/cgi-bin/search.pl?query=&fecha=2026-10-28"
        gaceta_pdf = BASE + "/one.pdf"
        tramites_pdf = BASE + "/pub/tramites/MINAE/manual-2025-v2.pdf"
        fallo_page = BASE + "/BusquedaAPI/DetalleFallo?fallo=1"
        fallo_pdf = BASE + "/fallo.pdf"
        cases = (
            (gaceta, "2026-10-27", {
                page: Response(page, f'<a href="{gaceta_pdf}">PDF</a>'.encode()),
                gaceta_pdf: Response(gaceta_pdf, PDF, content_type="application/pdf")}),
            (tramites, "0", {tramites_pdf: Response(tramites_pdf, PDF, content_type="application/pdf")}),
            (poder_judicial, "0", {
                fallo_page: Response(fallo_page, f'<a href="{fallo_pdf}">PDF</a>'.encode()),
                fallo_pdf: Response(fallo_pdf, PDF, content_type="application/pdf")}),
        )
        for module, before, routes in cases:
            with self.subTest(module=module.__name__):
                source = self.source(module, before)
                self.assertEqual(self.run_session(module, source, routes)[0], "downloaded")
                document = next(Path(source["download_dir"]).rglob("*.pdf"))
                document.write_bytes(b"different bytes")
                Path(source["state_file"]).write_text(before)
                result, _ = self.run_session(module, source, routes)
                self.assertEqual(result, "downloaded")
                self.assertEqual(document.read_bytes(), b"different bytes")
                self.assertEqual(len(list(Path(source["download_dir"]).rglob("*.pdf"))), 2)
                self.assertNotEqual(Path(source["state_file"]).read_text(), before)

    def test_scanners_do_not_mark_done_after_unsuccessful_acquisition(self):
        modules = (asamblea, conare_kimuk, instituciones_legacy, ucr_kerwa, una_repositorio)
        pdf = BASE + "/one.pdf"
        page = Response(BASE, f'<a href="{pdf}">PDF</a>'.encode())
        good = {BASE: page, pdf: Response(pdf, PDF, content_type="application/pdf")}
        cases = (
            ("page_http", {**good, BASE: Response(BASE, b"bad", 503)}, None, "failed"),
            ("page_timeout", {**good, BASE: requests.Timeout("offline")}, None, "failed"),
            ("page_empty", {**good, BASE: Response(BASE, b"")}, None, "site_changed"),
            ("pdf_http", {**good, pdf: Response(pdf, b"bad", 503)}, None, "failed"),
            ("pdf_timeout", {**good, pdf: requests.Timeout("offline")}, None, "failed"),
            ("pdf_invalid", {**good, pdf: Response(pdf, b"bad")}, None, "invalid_document"),
            ("disk", good, PermissionError("read only"), "failed"),
        )
        for module in modules:
            for label, routes, save_error, status in cases:
                with self.subTest(module=module.__name__, label=label):
                    source = self.source(module)
                    result, _ = self.run_session(module, source, routes, save_error)
                    self.assertEqual(result.status, status)
                    self.assert_retained(source, "seed")
                    recovered, calls = self.run_session(module, source, good)
                    self.assertEqual(recovered, "downloaded")
                    self.assertEqual(calls, [BASE, pdf])
                    self.assertEqual(Path(source["state_file"]).read_text(), "done")
                    self.assertEqual(len(list(Path(source["download_dir"]).rglob("*.pdf"))), 1)

    def test_scanners_verified_empty_and_one_download_per_turn(self):
        modules = (asamblea, conare_kimuk, instituciones_legacy, ucr_kerwa, una_repositorio)
        one, two = BASE + "/one.pdf", BASE + "/two.pdf"
        page = Response(BASE, f'<a href="{one}">one</a><a href="{two}">two</a>'.encode())
        good = {BASE: page, one: Response(one, PDF, content_type="application/pdf"),
                two: Response(two, PDF, content_type="application/pdf")}
        for module in modules:
            with self.subTest(module=module.__name__):
                source = self.source(module)
                result, calls = self.run_session(module, source, good)
                self.assertEqual(result, "downloaded")
                self.assertEqual(calls, [BASE, one])
                self.assertEqual(len(list(Path(source["download_dir"]).rglob("*.pdf"))), 1)
                empty_source = self.source(module)
                empty, _ = self.run_session(module, empty_source, {BASE: Response(BASE, b"<html>No PDFs</html>")})
                self.assertEqual(empty, "skipped")
                self.assertEqual(Path(empty_source["state_file"]).read_text(), "done")

    def test_manager_reports_invalid_responses_as_failures(self):
        import core.crawler_manager as manager_module

        with contextlib.redirect_stdout(io.StringIO()):
            manager = CrawlerManager("isolated", "ti")
        manager.source_configs = {"source": {}}
        logs = self.root / "isolated/ti/_logs"
        logs.mkdir()
        manager.jsonl_file = logs / "run.jsonl"
        module = types.SimpleNamespace(download_one=lambda source: CrawlerResult(
            "invalid_document", "PDF signature missing; cursor retained", "source",
            attempted_url=BASE + "/bad.pdf", http_status=200))
        output = io.StringIO()
        with mock.patch.object(manager_module, "load_crawler", return_value=module):
            with contextlib.redirect_stdout(output):
                result = manager._run_task({"source_id": "source"})
        self.assertEqual(result.status, "invalid_document")
        self.assertEqual(manager.stats["failed"], 1)
        self.assertEqual(manager.stats["skipped"], 0)
        self.assertIn("source | invalid_document | HTTP 200", output.getvalue())
        event = json.loads(manager.jsonl_file.read_text().splitlines()[-1])
        self.assertEqual(event["result_status"], "invalid_document")
        self.assertEqual(event["attempted_url"], BASE + "/bad.pdf")


if __name__ == "__main__":
    unittest.main()

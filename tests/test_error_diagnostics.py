"""Offline regression tests for crawler failure reporting."""

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

from core.crawler_manager import CrawlerManager
from core.results import CrawlerResult
from clients.veredictum.crawlers.ti import pgr


POST_URL = "https://www.pgr.go.cr/item/"
PDF_URL = "https://www.pgr.go.cr/one.pdf?api_key=private-value"
ARCHIVE = b'<article class="post"><h2><a href="/item/">Item</a></h2></article>'
POST = f'<main><a href="{PDF_URL}">PDF</a></main>'.encode()
PDF = b"%PDF-1.4\nfixture\n%%EOF"


class Response:
    def __init__(self, url, content, status=200):
        self.url = url
        self.content = content
        self.status_code = status
        self.text = content.decode(errors="replace")


class Session:
    def __init__(self, pdf_response):
        self.pdf_response = pdf_response

    def get(self, url, **kwargs):
        if url == pgr.ARCHIVE_URL:
            return Response(url, ARCHIVE)
        if url == POST_URL:
            return Response(url, POST)
        if url == PDF_URL:
            if isinstance(self.pdf_response, Exception):
                raise self.pdf_response
            return self.pdf_response
        raise AssertionError(f"unexpected URL: {url}")


class ErrorDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        root = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.root = Path(root)
        self.stack.enter_context(mock.patch.dict(os.environ, {"METACRAWLER_DATA_ROOT": root}))
        self.stack.enter_context(mock.patch.object(
            requests.sessions.Session, "request",
            side_effect=AssertionError("external network request attempted")))
        with contextlib.redirect_stdout(io.StringIO()):
            self.manager = CrawlerManager("test_client", "ti")
        self.manager.source_configs = {"pgr": {}, "legacy": {}}
        logs = self.root / "test_client/ti/_logs"
        logs.mkdir()
        self.manager.log_file = logs / "run.log"
        self.manager.jsonl_file = logs / "run.jsonl"

    def _run(self, module, source):
        output = io.StringIO()
        with mock.patch("core.crawler_manager.load_crawler", return_value=module):
            with contextlib.redirect_stdout(output):
                result = self.manager._run_task({"source_id": source})
        event = json.loads(self.manager.jsonl_file.read_text().splitlines()[-1])
        return result, event, output.getvalue()

    def _run_pgr(self, response, save_error=None):
        with mock.patch.object(pgr.requests, "Session", return_value=Session(response)):
            if save_error is None:
                return self._run(pgr, "pgr")
            with mock.patch.object(pgr, "save_download", side_effect=save_error):
                return self._run(pgr, "pgr")

    def test_http_failure_retains_diagnostics_and_reports_terminal(self):
        result, event, output = self._run_pgr(Response(PDF_URL, b"unavailable", 503))
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.http_status, 503)
        self.assertEqual(event["result_status"], "failed")
        self.assertEqual(event["http_status"], 503)
        self.assertEqual(event["error_type"], "HTTPError")
        self.assertIn("HTTP 503", event["error_message"])
        self.assertTrue(event["retryable"])
        self.assertEqual(event["attempted_url"], "https://www.pgr.go.cr/one.pdf")
        self.assertIn("pgr | HTTPError | HTTP 503", output)
        self.assertIn("HTTP 503", output)
        self.assertNotIn("private-value", self.manager.jsonl_file.read_text() + output)
        self.assertEqual(list((self.root / "test_client/ti/pgr").glob("*.pdf")), [])

    def test_connection_failure_retains_diagnostics(self):
        error = requests.ConnectionError(f"connection lost at {PDF_URL}")
        result, event, output = self._run_pgr(error)
        self.assertEqual(result.error_type, "ConnectionError")
        self.assertIsNone(event["http_status"])
        self.assertEqual(event["error_type"], "ConnectionError")
        self.assertIn("connection lost", event["error_message"])
        self.assertIn("pgr | ConnectionError", output)
        self.assertNotIn("private-value", self.manager.jsonl_file.read_text() + output)

    def test_filesystem_failure_is_not_reported_as_request_failure(self):
        result, event, output = self._run_pgr(
            Response(PDF_URL, PDF), PermissionError("disk is read only"))
        self.assertEqual(result.reason, "PGR persistence failed; cursor retained")
        self.assertEqual(event["reason"], result.reason)
        self.assertEqual(event["error_type"], "PermissionError")
        self.assertIsNone(event["http_status"])
        self.assertIn("pgr | PermissionError", output)
        self.assertIn("PGR persistence failed", output)
        self.assertIn("disk is read only", output)
        self.assertNotIn("request failed", output)
        self.assertEqual((self.root / "test_client/ti/_state/pgr.json").read_text(), "{}")
        self.assertEqual(list((self.root / "test_client/ti/pgr").glob("*.pdf")), [])

    def test_all_result_fields_and_legacy_strings_remain_compatible(self):
        structured = CrawlerResult(
            "failed", "service unavailable", "legacy", attempted_url="https://user:pass@example.test/x?token=private-value",
            http_status=429, error_type="HTTPError", error_message="Authorization: Bearer secret-value",
            retryable=True, retry_at="later", backoff_class="long")
        module = types.SimpleNamespace(download_one=lambda source: structured)
        _, event, output = self._run(module, "legacy")
        self.assertEqual(event["retry_at"], "later")
        self.assertEqual(event["backoff_class"], "long")
        self.assertEqual(event["attempted_url"], "https://example.test/x")
        self.assertEqual(event["error_message"], "Authorization: Bearer [REDACTED]")
        self.assertIn("legacy | HTTPError | HTTP 429", output)
        self.assertNotIn("secret-value", output)
        for legacy in ("skipped", "failed", "downloaded"):
            with self.subTest(legacy=legacy):
                module = types.SimpleNamespace(download_one=lambda source, value=legacy: value)
                result, event, _ = self._run(module, "legacy")
                self.assertEqual(result.status, legacy)
                self.assertEqual(event["reason"], f"legacy_result:{legacy}")
                self.assertIn("attempted_url", event)

    def test_unhandled_exception_keeps_diagnostics_and_redacts_traceback(self):
        def raise_error(source):
            raise RuntimeError("token=private-value failed")

        module = types.SimpleNamespace(download_one=raise_error)
        result, event, output = self._run(module, "legacy")
        self.assertEqual(result.error_type, "RuntimeError")
        self.assertEqual(event["error_type"], "RuntimeError")
        self.assertIn("exception", event)
        self.assertIn("legacy | RuntimeError", output)
        self.assertNotIn("private-value", self.manager.jsonl_file.read_text() + output)


if __name__ == "__main__":
    unittest.main()

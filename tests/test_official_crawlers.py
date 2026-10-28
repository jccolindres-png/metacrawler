"""Offline fixtures for the two official Costa Rican acquisition flows."""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "Backend")]
from clients.veredictum.crawlers.ti import pgr, sinalevi

FIXTURES = ROOT / "tests" / "fixtures"
PDF = b"%PDF-1.4\nfixture bytes\n%%EOF"


def fixture(name):
    return (FIXTURES / name).read_bytes()


class Response:
    def __init__(self, content, url, status=200, content_type="text/html"):
        self.content = content
        self.url = url
        self.status_code = status
        self.headers = {"Content-Type": content_type}
        self.text = content.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.content)


class RoutedSession:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        result = self.routes.get(("GET", url))
        if result is None:
            raise AssertionError(f"unmocked GET {url}")
        if isinstance(result, Exception):
            raise result
        return result

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        result = self.routes.get(("POST", url))
        if result is None:
            raise AssertionError(f"unmocked POST {url}")
        if isinstance(result, Exception):
            raise result
        return result


class OfficialCrawlerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = {"download_dir": str(self.root / "documents"),
                       "state_file": str(self.root / "cursor.json")}

    def _run(self, module, routes):
        session = RoutedSession(routes)
        with mock.patch.object(module.requests, "Session", return_value=session):
            result = module.download_one(self.source)
        return result, session

    def _state(self):
        return json.loads(Path(self.source["state_file"]).read_text())

    def _sidecar(self, path, url):
        metadata = json.loads(Path(str(path) + ".source.json").read_text())
        self.assertEqual(metadata["source_url"], url)
        self.assertEqual(metadata["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(metadata["size_bytes"], len(path.read_bytes()))

    def pgr_routes(self):
        base = "https://www.pgr.go.cr"
        return {
            ("GET", pgr.ARCHIVE_URL): Response(fixture("pgr_archive_1.html"), pgr.ARCHIVE_URL),
            ("GET", base + "/publicaciones/page/2/"): Response(
                fixture("pgr_archive_2.html"), base + "/publicaciones/page/2/"),
            ("GET", base + "/publicacion-uno/"): Response(
                fixture("pgr_post_1.html"), base + "/publicacion-uno/"),
            ("GET", base + "/publicacion-dos/"): Response(
                fixture("pgr_post_2.html"), base + "/publicacion-dos/"),
            ("GET", base + "/publicacion-tres/"): Response(
                fixture("pgr_post_3.html"), base + "/publicacion-tres/"),
            **{("GET", base + "/wp-content/uploads/" + name): Response(
                PDF, base + "/wp-content/uploads/" + name, content_type="application/pdf")
                for name in ("uno.pdf", "uno-anexo.pdf", "tres.pdf?download=1")},
        }

    def test_pgr_relative_links_pagination_cursor_and_provenance(self):
        routes = self.pgr_routes()
        for expected in ("uno.pdf", "uno-anexo.pdf", "tres.pdf?download=1"):
            result, session = self._run(pgr, routes)
            self.assertEqual(result, "downloaded")
            pdf_calls = [call for call in session.calls if call[1].endswith(expected)]
            self.assertEqual(len(pdf_calls), 1)
            self.assertEqual(len(list((self.root / "documents").glob("*.pdf"))),
                             ("uno.pdf", "uno-anexo.pdf", "tres.pdf?download=1").index(expected) + 1)
            path = next(path for path in (self.root / "documents").glob("*.pdf")
                        if expected.split(".pdf")[0] in path.name)
            self._sidecar(path, pdf_calls[0][1])
            if expected == "uno-anexo.pdf":
                # The next run can advance the archive page without fetching old posts.
                result, session = self._run(pgr, routes)
                self.assertEqual(result.status, "no_new_documents")
                self.assertEqual(self._state()["page_url"],
                                 "https://www.pgr.go.cr/publicaciones/page/2/")
        self.assertEqual(len(list((self.root / "documents").glob("*.pdf"))), 3)
        self.assertEqual(self._state()["page_url"], "https://www.pgr.go.cr/publicaciones/page/2/")

    def test_pgr_failure_keeps_position_and_empty_archive_is_distinct(self):
        routes = self.pgr_routes()
        routes[("GET", "https://www.pgr.go.cr/publicacion-uno/")] = requests.Timeout("offline")
        result, _ = self._run(pgr, routes)
        self.assertEqual(result.status, "failed")
        self.assertTrue(result.retryable)
        self.assertFalse(Path(self.source["state_file"]).exists())
        routes[("GET", pgr.ARCHIVE_URL)] = Response(b"<html><body></body></html>", pgr.ARCHIVE_URL)
        result, _ = self._run(pgr, routes)
        self.assertEqual(result.status, "site_changed")
        self.assertFalse(Path(self.source["state_file"]).exists())
        routes = self.pgr_routes()
        routes[("GET", "https://www.pgr.go.cr/wp-content/uploads/uno.pdf")] = requests.Timeout("offline")
        result, _ = self._run(pgr, routes)
        self.assertEqual(result.status, "failed")
        self.assertFalse(Path(self.source["state_file"]).exists())
        routes[("GET", "https://www.pgr.go.cr/wp-content/uploads/uno.pdf")] = Response(
            b"<html>maintenance</html>", "https://www.pgr.go.cr/wp-content/uploads/uno.pdf",
            status=503)
        result, _ = self._run(pgr, routes)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.http_status, 503)
        self.assertFalse(Path(self.source["state_file"]).exists())
        Path(self.source["state_file"]).write_text(json.dumps({
            "page_url": "https://www.pgr.go.cr/publicaciones/page/2/",
            "post_index": 0, "pdf_index": 0, "seen_posts": [], "seen_pdfs": []
        }))
        routes = self.pgr_routes()
        routes[("GET", "https://www.pgr.go.cr/publicaciones/page/2/")] = Response(
            b"<html><body><main>No results</main></body></html>",
            "https://www.pgr.go.cr/publicaciones/page/2/")
        result, _ = self._run(pgr, routes)
        self.assertEqual(result.status, "no_new_documents")
        self.assertEqual(self._state()["page_url"], pgr.ARCHIVE_URL)

    def test_pgr_skips_historical_name_without_overwrite(self):
        routes = self.pgr_routes()
        old = self.root / "documents" / "uno.pdf"
        old.parent.mkdir()
        old.write_bytes(b"historical")
        result, session = self._run(pgr, routes)
        self.assertEqual(result, "downloaded")
        self.assertEqual(old.read_bytes(), b"historical")
        self.assertFalse(any(call[1].endswith("/uno.pdf") for call in session.calls))

    def sinalevi_routes(self, search=None):
        search = fixture("sinalevi_search_1.json") if search is None else search
        return {
            ("GET", sinalevi.SEARCH_URL): Response(search, sinalevi.SEARCH_URL, content_type="application/json"),
            ("GET", sinalevi.DETAIL_URL): Response(fixture("sinalevi_detail.html"), sinalevi.DETAIL_URL),
            ("POST", sinalevi.TEXT_URL): Response(fixture("sinalevi_text.json"), sinalevi.TEXT_URL,
                                                   content_type="application/json"),
            ("POST", sinalevi.PDF_URL): Response(PDF, sinalevi.PDF_URL, content_type="application/pdf"),
        }

    def test_sinalevi_official_flow_cursor_one_pdf_and_provenance(self):
        result, session = self._run(sinalevi, self.sinalevi_routes())
        self.assertEqual(result, "downloaded")
        self.assertEqual(self._state()["item_index"], 1)
        self.assertEqual(len(list((self.root / "documents").glob("*.pdf"))), 1)
        path = next((self.root / "documents").glob("*.pdf"))
        self._sidecar(path, sinalevi.PDF_URL)
        pdf_call = next(call for call in session.calls if call[1] == sinalevi.PDF_URL)
        self.assertIn("contenedorTexto", pdf_call[2]["json"]["html"])
        search_call = next(call for call in session.calls if call[1] == sinalevi.SEARCH_URL)
        self.assertEqual(search_call[2]["params"]["pagina"], 1)

    def test_sinalevi_failures_keep_cursor_for_retry(self):
        for stage in (sinalevi.SEARCH_URL, sinalevi.DETAIL_URL, sinalevi.TEXT_URL, sinalevi.PDF_URL):
            with self.subTest(stage=stage):
                Path(self.source["state_file"]).write_text("{}")
                routes = self.sinalevi_routes()
                verb = "POST" if stage in (sinalevi.TEXT_URL, sinalevi.PDF_URL) else "GET"
                routes[(verb, stage)] = requests.Timeout("offline")
                result, _ = self._run(sinalevi, routes)
                self.assertEqual(result.status, "failed")
                self.assertTrue(result.retryable)
                self.assertEqual(Path(self.source["state_file"]).read_text(), "{}")
        routes = self.sinalevi_routes()
        routes[("POST", sinalevi.PDF_URL)] = Response(b"<html>error</html>", sinalevi.PDF_URL)
        result, _ = self._run(sinalevi, routes)
        self.assertEqual(result.status, "invalid_document")
        self.assertEqual(Path(self.source["state_file"]).read_text(), "{}")

    def test_sinalevi_pagination_duplicate_and_empty_page(self):
        # A full result page advances to the next official JSON page.
        full = [{"IdFichaNorma": i, "IdVersionNorma": i + 100} for i in range(1, 11)]
        state = {"query_index": 0, "page": 1, "item_index": 9, "seen": ["10:110"]}
        Path(self.source["state_file"]).write_text(json.dumps(state))
        existing = self.root / "documents" / "sinalevi_norma_10_110.pdf"
        existing.parent.mkdir()
        existing.write_bytes(PDF)
        result, session = self._run(sinalevi, self.sinalevi_routes(json.dumps(full).encode()))
        self.assertEqual(result.status, "duplicate")
        self.assertEqual(self._state()["page"], 2)
        self.assertEqual(len(session.calls), 1)
        result, session = self._run(sinalevi, self.sinalevi_routes(b"[]"))
        self.assertEqual(result.status, "no_new_documents")
        self.assertEqual(self._state()["query_index"], 1)
        self.assertEqual(self._state()["page"], 1)
        self.assertEqual(session.calls[0][2]["params"]["pagina"], 2)

    def test_sinalevi_existing_incomplete_file_and_old_cursor(self):
        path = self.root / "documents" / "sinalevi_norma_108074_152717.pdf"
        path.parent.mkdir()
        path.write_bytes(b"%PDF-truncated")
        result, session = self._run(sinalevi, self.sinalevi_routes())
        self.assertEqual(result.status, "manual_review")
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(path.read_bytes(), b"%PDF-truncated")
        Path(self.source["state_file"]).write_text("7")
        result, _ = self._run(sinalevi, self.sinalevi_routes())
        self.assertEqual(result.status, "manual_review")
        self.assertEqual(Path(self.source["state_file"]).read_text(), "7")


if __name__ == "__main__":
    unittest.main()

import hashlib
import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen
from http.server import ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("uc_preview", ROOT / "scripts/workflow/preview.py")
preview = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preview)

class LivePreviewTests(unittest.TestCase):
    def test_missing_manifest_is_pending(self):
        with tempfile.TemporaryDirectory() as d:
            out = preview.load_status(d)
            self.assertEqual(out["state"], "pending")
            self.assertEqual(out["completed"], 0)

    def test_summary_is_redacted_and_progress_updated(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            (folder / "manifest.json").write_text(json.dumps({
                "schema_version": 1, "state": "running",
                "transport": "ssh", "target": "secret-target-alias",
                "expected_probes": 8,
                "items": [
                    {"category": "identity", "name": "os", "status": "ok",
                     "stage": "bootstrap", "error": "SECRET_TOKEN"},
                    {"category": "network", "name": "ip-link", "status": "error",
                     "stage": "detail", "error": "192.0.2.33"}
                ],
                "skipped": [{"name": "dt-source", "reason": "secret private path"}]
            }))
            status = preview.load_status(folder)
            self.assertEqual(status["state"], "running")
            self.assertEqual(status["stage"], "detail")
            self.assertEqual(status["total"], 8)
            self.assertEqual(status["completed"], 2)
            self.assertEqual(status["categories"]["network"]["other"], 1)
            serialized = json.dumps(status)
            for secret in ("SECRET_TOKEN", "192.0.2.33", "secret-target-alias", "secret private path"):
                self.assertNotIn(secret, serialized)

    def test_managed_session_blocked_and_partial_are_not_reported_as_incomplete(self):
        for expected in ("blocked", "partial"):
            with self.subTest(expected=expected):
                with tempfile.TemporaryDirectory() as d:
                    (Path(d) / "manifest.json").write_text(json.dumps({
                        "schema_version": 1, "state": expected,
                        "workflow_version": "device-session-v1",
                        "expected_probes": 20,
                        "target": "private-ip", "items": [
                            {"category": "identity", "name": "kernel", "status": "ok"}
                        ]
                    }))
                    status = preview.load_status(d)
                    self.assertEqual(status["state"], expected)
                    self.assertEqual(status["total"], 20)
                    self.assertEqual(status["completed"], 1)
                    self.assertNotIn("private-ip", json.dumps(status))

    def test_http_read_only_status_and_no_raw_file(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            (folder / "manifest.json").write_text(json.dumps({"schema_version": 1, "state": "complete", "items": []}))
            server = ThreadingHTTPServer(("127.0.0.1", 0), preview.make_handler(folder))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                with urlopen(base + "/api/status") as response:
                    result = json.load(response)
                    self.assertEqual(result["state"], "complete")
                from urllib.error import HTTPError
                with self.assertRaises(HTTPError) as error:
                    urlopen(base + "/manifest.json")
                self.assertEqual(error.exception.code, 404)
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

if __name__ == "__main__":
    unittest.main()

"""Loopback UI access-control and API integration tests."""

import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from releasecraft.web import make_server
from test_core import LICENSE


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        source = base / "source"
        source.mkdir()
        (source / "main.py").write_text("print(1)")
        (source / "README.md").write_text("# Sample")
        (source / "LICENSE").write_text(LICENSE)
        self.server = make_server(source, base / "work", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port
        self.token = self.server.session_url.split("#")[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def req(self, path, method="GET", body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port)
        c.request(
            method, path, json.dumps(body) if body is not None else None, headers or {}
        )
        r = c.getresponse()
        data = r.read()
        status = r.status
        c.close()
        return status, data

    def auth(self):
        return {
            "Origin": f"http://127.0.0.1:{self.port}",
            "X-Releasecraft-Token": self.token,
            "Content-Type": "application/json",
        }

    def test_page(self):
        status, body = self.req("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Releasecraft", body)
        self.assertNotIn(self.token.encode(), body)

    def test_token_required(self):
        self.assertEqual(self.req("/api/state")[0], 404)

    def test_cross_origin_rejected(self):
        h = self.auth()
        h["Origin"] = "https://invalid.example"
        self.assertEqual(self.req("/api/analyze", "POST", {}, h)[0], 403)

    def test_dns_rebinding_rejected(self):
        h = self.auth()
        h["Host"] = "invalid.example"
        self.assertEqual(self.req("/api/analyze", "POST", {}, h)[0], 403)

    def test_no_commands_api(self):
        self.assertEqual(self.req("/api/execute", "POST", {}, self.auth())[0], 404)

    def test_build_requires_plan(self):
        self.assertEqual(self.req("/api/build", "POST", {}, self.auth())[0], 400)

    def test_full_flow_and_repeat(self):
        status, body = self.req("/api/analyze", "POST", {"policy": {}}, self.auth())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "PLANNED")
        a = self.req("/api/build", "POST", {}, self.auth())
        b = self.req("/api/build", "POST", {}, self.auth())
        self.assertEqual(a, b)
        self.assertEqual(json.loads(a[1])["status"], "CANDIDATE")

    def test_invalid_policy_recoverable(self):
        self.assertEqual(
            self.req("/api/analyze", "POST", {"policy": {"wrong": 1}}, self.auth())[0],
            400,
        )
        self.assertEqual(
            self.req("/api/analyze", "POST", {"policy": {}}, self.auth())[0], 200
        )


if __name__ == "__main__":
    unittest.main()

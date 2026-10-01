"""Loopback UI access-control and API integration tests."""

import http.client
import json
from pathlib import Path
import tempfile
import threading
import socket
import time
import unittest
from unittest.mock import patch
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

    def test_rejected_fragmented_post_returns_complete_403_without_analysis(self):
        for changed in ({"Origin": "https://invalid.example"}, {"Host": "invalid.example"}, {"X-Releasecraft-Token": "wrong"}):
            for delay in (0.001, 0.01):
                with self.subTest(rejected_field=next(iter(changed)), delay=delay), patch("releasecraft.web.analyze") as analyze:
                    headers = {"Host": f"127.0.0.1:{self.port}", **self.auth(), **changed, "Content-Length": "2", "Connection": "close"}
                    with socket.create_connection(("127.0.0.1", self.port), timeout=3) as connection:
                        connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                        request = "POST /api/analyze HTTP/1.1\r\n" + "".join(f"{key}: {value}\r\n" for key, value in headers.items()) + "\r\n"
                        connection.sendall(request.encode("ascii"))
                        time.sleep(delay)
                        connection.sendall(b"{}")
                        response = http.client.HTTPResponse(connection)
                        response.begin()
                        body = response.read()
                        self.assertEqual(response.status, 403)
                        self.assertEqual(int(response.getheader("Content-Length")), len(body))
                        self.assertEqual(json.loads(body), {"error": "Origin or session token rejected"})
                        response.close()
                    analyze.assert_not_called()
        self.assertEqual(json.loads(self.req("/api/state", headers=self.auth())[1])["plan"], None)

    def test_rejected_post_does_not_wait_for_oversized_or_invalid_length(self):
        for size in ("65537", "invalid"):
            with self.subTest(length=size), patch("releasecraft.web.analyze") as analyze:
                headers = {**self.auth(), "Origin": "https://invalid.example", "Content-Length": size}
                connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
                try:
                    connection.request("POST", "/api/analyze", headers=headers)
                    response = connection.getresponse()
                    self.assertEqual(response.status, 403)
                    response.read()
                finally:
                    connection.close()
                analyze.assert_not_called()
        self.assertEqual(self.req("/")[0], 200)

    def test_rejected_incomplete_body_has_bounded_wait(self):
        headers = {**self.auth(), "Origin": "https://invalid.example", "Content-Length": "2"}
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        with patch("releasecraft.web.analyze") as analyze:
            try:
                connection.request("POST", "/api/analyze", headers=headers)
                response = connection.getresponse()
                self.assertEqual(response.status, 403)
                response.read()
            finally:
                connection.close()
            analyze.assert_not_called()
        self.assertEqual(self.req("/")[0], 200)

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

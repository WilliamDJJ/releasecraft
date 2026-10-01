"""Loopback-only UI. Never executes target-project commands."""

from __future__ import annotations
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
from .analyze import analyze
from .build import assemble, verify_cached
from .policy import load_policy
from .safety import ReleaseError, atomic_json, canonical, separate


def make_server(source, work, port=8765):
    source = Path(source).resolve()
    work = Path(work).resolve()
    separate(source, work)
    if not source.is_dir():
        raise ReleaseError("Source must exist")
    work.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    state = {"plan": None, "result": None}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, data, mime="application/json"):
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'",
            )
            self.end_headers()
            self.wfile.write(data if isinstance(data, bytes) else canonical(data))

        def valid_host(self):
            return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

        def do_GET(self):
            if not self.valid_host():
                self.send(403, {"error": "Invalid Host"})
                return
            if self.path == "/":
                page = Path(__file__).with_name("ui.html").read_bytes()
                self.send(200, page, "text/html; charset=utf-8")
                return
            if self.path == "/api/state" and secrets.compare_digest(
                self.headers.get("X-Releasecraft-Token", ""), token
            ):
                self.send(200, state)
                return
            self.send(404, {"error": "Not found"})

        def do_POST(self):
            expected = f"http://127.0.0.1:{self.server.server_port}"
            if (
                not self.valid_host()
                or self.headers.get("Origin") != expected
                or not secrets.compare_digest(
                    self.headers.get("X-Releasecraft-Token", ""), token
                )
            ):
                self.send(403, {"error": "Origin or session token rejected"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 65536:
                    raise ValueError()
                body = json.loads(self.rfile.read(size))
                if self.path == "/api/analyze":
                    state["plan"] = analyze(
                        source, load_policy(value=body.get("policy", {}))
                    )
                    state["result"] = None
                    atomic_json(work / "plan.json", state["plan"])
                    self.send(200, state["plan"])
                elif self.path == "/api/build":
                    if state["plan"] is None:
                        raise ReleaseError("Analyze first")
                    dest = work / ("release-" + state["plan"]["plan_sha256"][:12])
                    if (
                        analyze(source, state["plan"]["policy"])["plan_sha256"]
                        != state["plan"]["plan_sha256"]
                    ):
                        raise ReleaseError("Source changed")
                    if dest.exists():
                        state["result"] = verify_cached(
                            dest / "release.zip", state["plan"]
                        )
                    else:
                        state["result"] = assemble(source, state["plan"], dest)
                    self.send(200, state["result"])
                else:
                    self.send(404, {"error": "Unknown operation"})
            except (OSError, ReleaseError, ValueError, KeyError, TypeError):
                self.send(
                    400,
                    {
                        "status": "FAILED",
                        "error": "Operation rejected; inspect plan blockers and policy",
                    },
                )

    server = HTTPServer(("127.0.0.1", port), Handler)
    server.session_url = f"http://127.0.0.1:{server.server_port}/#" + token
    return server


def serve(source, work, port=8765):
    server = make_server(source, work, port)
    print("Releasecraft local UI: " + server.session_url, flush=True)
    print(
        "Source is read-only. The UI never executes project code. Ctrl+C stops the server.",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

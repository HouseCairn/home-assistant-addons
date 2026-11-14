"""The start test's browser (tests/start/first_admin.py) behind the stand-in for Ingress (ingress.py).

Standard library only, no Docker: python3 -m unittest discover -s tests -v

The app here accepts every same-site POST, whatever its `Origin`: it cannot have the
bug of issue #11. What is under test is the test itself: the Ingress case must come
with Home Assistant's `Referrer-Policy: no-referrer` (which makes a browser send
`Origin: null`), and must fail when it does not, rather than pass on another case.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

START = Path(__file__).resolve().parent / "start"
_spec = importlib.util.spec_from_file_location("housecairn_start_ingress", START / "ingress.py")
assert _spec and _spec.loader
ingress = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ingress)

TOKEN = "0123456789abcdef" * 4
BASE = f"/api/hassio_ingress/{TOKEN}"


class PermissiveApp(BaseHTTPRequestHandler):
    """Serves the setup form; refuses the POSTs of another site, accepts the others."""

    protocol_version = "HTTP/1.1"
    policy: str | None = None  # the Referrer-Policy the app itself sends, if any

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass

    def reply(self, status: int, body: bytes = b"", headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        prefix = self.headers.get("X-Ingress-Path", "")
        if self.path == "/setup/":
            form = (
                f'<form method="post" action="{prefix}/setup/">'
                '<input type="hidden" name="csrfmiddlewaretoken" value="token"></form>'
            )
            headers = {"Content-Type": "text/html"}
            if self.policy:
                headers["Referrer-Policy"] = self.policy
            self.reply(200, form.encode(), headers)
        elif self.path == "/instance/":
            self.reply(200, b"overview", {"Content-Type": "text/html"})
        else:
            self.reply(404)

    def do_POST(self) -> None:  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.reply(403)
        else:
            prefix = self.headers.get("X-Ingress-Path", "")
            self.reply(302, headers={"Location": f"http://x{prefix}/instance/"})


class quiet_ingress(ingress.Ingress):  # noqa: N801 (a handler class)
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


def serve(handler: type[BaseHTTPRequestHandler]) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class FirstAdminTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = serve(PermissiveApp)
        self.addCleanup(self.app.server_close)
        self.addCleanup(self.app.shutdown)
        old = os.environ.get("APP_URL")
        os.environ["APP_URL"] = f"http://127.0.0.1:{self.app.server_port}"
        self.addCleanup(lambda: os.environ.__setitem__("APP_URL", old) if old else os.environ.pop("APP_URL", None))
        PermissiveApp.policy = None
        self.addCleanup(setattr, PermissiveApp, "policy", None)

    def run_browser(self, port: int, *extra: str, base: str = "") -> tuple[int, dict[str, object]]:
        proc = subprocess.run(  # noqa: S603 (a test)
            [
                sys.executable, "-I", str(START / "first_admin.py"),
                "--connect", f"127.0.0.1:{port}", "--host", "homeassistant.local:8123",
                "--base", base, "--code", "CODE", *extra,
            ],
            capture_output=True, text=True, timeout=60, check=False,
        )  # fmt: skip
        return proc.returncode, json.loads(proc.stdout)

    def ingress_port(self) -> int:
        proxy = serve(quiet_ingress)
        self.addCleanup(proxy.server_close)
        self.addCleanup(proxy.shutdown)
        return proxy.server_port

    def test_ingress_sets_the_policy_of_core_and_the_case_passes(self) -> None:
        code, report = self.run_browser(
            self.ingress_port(), "--frame", "--expect-policy", "no-referrer", base=BASE
        )
        self.assertEqual(code, 0, report)
        self.assertEqual(report["result"], "PASS")
        self.assertEqual(report["get"]["referrer_policy"], "no-referrer")  # type: ignore[index]
        self.assertEqual(report["post"]["origin"], "null")  # type: ignore[index]

    def test_a_stand_in_without_the_header_fails_even_if_the_app_accepts_the_post(self) -> None:
        # Mutant: Ingress forgets Core's Referrer-Policy. Without the requirement the case
        # sends a normal Origin and passes on any app, the one with issue #11 included.
        saved = dict(ingress.CORE_RESPONSE_HEADERS)
        self.addCleanup(ingress.CORE_RESPONSE_HEADERS.update, saved)
        ingress.CORE_RESPONSE_HEADERS.pop("Referrer-Policy", None)
        port = self.ingress_port()
        code, report = self.run_browser(port, "--expect-policy", "no-referrer", base=BASE)
        self.assertEqual(code, 1)
        self.assertIn("missing", str(report["error"]))
        self.assertNotIn("post", report)  # failed before any POST
        # Without the requirement, the same case passes: that is the hole being closed.
        code, report = self.run_browser(port, base=BASE)
        self.assertEqual((code, report["result"]), (0, "PASS"))

    def test_another_policy_fails(self) -> None:
        PermissiveApp.policy = "same-origin"
        direct = serve(PermissiveApp)
        self.addCleanup(direct.server_close)
        self.addCleanup(direct.shutdown)
        code, report = self.run_browser(direct.server_port, "--expect-policy", "no-referrer")
        self.assertEqual(code, 1)
        self.assertIn("same-origin", str(report["error"]))

    def test_the_port_case_needs_no_policy(self) -> None:
        code, report = self.run_browser(self.app.server_port)
        self.assertEqual((code, report["result"]), (0, "PASS"))
        self.assertEqual(report["post"]["origin"], "http://homeassistant.local:8123")  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()

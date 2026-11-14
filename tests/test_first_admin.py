"""The start test's browser (tests/start/first_admin.py) behind the stand-in for Ingress (ingress.py).

Standard library only, no Docker: python3 -m unittest discover -s tests -v

The app here accepts every same-site POST, whatever its `Origin` (unless a test sets
`refuse_null`): it cannot have the bug of issue #11. What is under test is the test itself:
the Ingress case must come with Home Assistant's `Referrer-Policy: no-referrer` header, and
must fail when it does not, rather than pass on another case; the browser must apply the
page's `<meta name="referrer">` over that header, so that a page without the meta (image
0.3.1) still sends `Origin: null` and is refused, and one with it sends its origin.
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

_spec = importlib.util.spec_from_file_location("housecairn_start_first_admin", START / "first_admin.py")
assert _spec and _spec.loader
first_admin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(first_admin)

TOKEN = "0123456789abcdef" * 4
BASE = f"/api/hassio_ingress/{TOKEN}"


class PermissiveApp(BaseHTTPRequestHandler):
    """Serves the setup form; refuses the POSTs of another site, accepts the others."""

    protocol_version = "HTTP/1.1"
    policy: str | None = None  # the Referrer-Policy the app itself sends, if any
    head = ""  # markup for the page's <head>, such as a <meta name="referrer">
    refuse_null = False  # behave as the app of issue #11: 403 for `Origin: null`

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
                f"<head>{self.head}</head>"
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
        if self.headers.get("Sec-Fetch-Site") == "cross-site" or (
            self.refuse_null and self.headers.get("Origin") == "null"
        ):
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
        for name, default in (("policy", None), ("head", ""), ("refuse_null", False)):
            setattr(PermissiveApp, name, default)
            self.addCleanup(setattr, PermissiveApp, name, default)

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

    def test_the_meta_replaces_the_header_and_the_post_carries_the_origin(self) -> None:
        # The image of 0.3.2: Core's header says no-referrer, the page's meta says same-origin.
        PermissiveApp.head = '<meta name="referrer" content="same-origin">'
        PermissiveApp.refuse_null = True
        code, report = self.run_browser(
            self.ingress_port(), "--frame", "--expect-policy", "no-referrer", base=BASE
        )
        self.assertEqual(code, 0, report)
        get = report["get"]
        self.assertEqual((get["referrer_policy"], get["effective_referrer_policy"]), ("no-referrer", "same-origin"))  # type: ignore[index]
        self.assertEqual(report["post"]["origin"], "http://homeassistant.local:8123")  # type: ignore[index]
        self.assertEqual([p["status"] for p in report["cross_site_posts"]], [403, 403])  # type: ignore[attr-defined]

    def test_a_page_without_the_meta_still_sends_null_and_fails(self) -> None:
        # The image of 0.3.1 (issue #11): no meta, so the header wins, `Origin: null`, 403.
        # The start test has to keep catching a regression of the fix.
        PermissiveApp.refuse_null = True
        code, report = self.run_browser(
            self.ingress_port(), "--frame", "--expect-policy", "no-referrer", base=BASE
        )
        self.assertEqual(code, 1, report)
        self.assertEqual(report["result"], "FAIL")
        self.assertEqual(report["get"]["effective_referrer_policy"], "no-referrer")  # type: ignore[index]
        self.assertEqual((report["post"]["origin"], report["post"]["status"]), ("null", 403))  # type: ignore[index]

    def test_an_invalid_meta_is_ignored_and_fails_like_no_meta(self) -> None:
        PermissiveApp.head = '<meta name="referrer" content="sometimes">'
        PermissiveApp.refuse_null = True
        code, report = self.run_browser(
            self.ingress_port(), "--frame", "--expect-policy", "no-referrer", base=BASE
        )
        self.assertEqual(code, 1, report)
        self.assertEqual(report["post"]["origin"], "null")  # type: ignore[index]


class EffectivePolicyTests(unittest.TestCase):
    def policy(self, header: str, *metas: str) -> str:
        body = "<html><head>" + "".join(metas) + "</head><body></body></html>"
        return first_admin.effective_policy(header, body)

    def test_header_alone(self) -> None:
        self.assertEqual(self.policy("no-referrer"), "no-referrer")
        self.assertEqual(self.policy(""), "")

    def test_a_valid_meta_replaces_the_header(self) -> None:
        self.assertEqual(self.policy("no-referrer", '<meta name="referrer" content="same-origin">'), "same-origin")

    def test_an_invalid_meta_is_ignored(self) -> None:
        self.assertEqual(self.policy("no-referrer", '<meta name="referrer" content="sometimes">'), "no-referrer")
        self.assertEqual(self.policy("no-referrer", '<meta name="referrer" content="">'), "no-referrer")
        self.assertEqual(self.policy("no-referrer", '<meta name="referrer">'), "no-referrer")

    def test_the_last_valid_meta_wins(self) -> None:
        metas = (
            '<meta name="referrer" content="origin">',
            '<meta name="referrer" content="same-origin">',
            '<meta name="referrer" content="bogus">',
        )
        self.assertEqual(self.policy("no-referrer", *metas), "same-origin")

    def test_case_and_spaces(self) -> None:
        self.assertEqual(self.policy("no-referrer", '<META NAME="Referrer" CONTENT="  Same-Origin ">'), "same-origin")

    def test_other_metas_do_not_count(self) -> None:
        self.assertEqual(self.policy("no-referrer", '<meta name="viewport" content="same-origin">'), "no-referrer")

    def test_origin_of_a_same_origin_post(self) -> None:
        origin = "http://homeassistant.local:8123"
        self.assertEqual(first_admin.request_origin("no-referrer", origin), "null")
        for policy in ("same-origin", "origin", "strict-origin-when-cross-origin", "unsafe-url", ""):
            self.assertEqual(first_admin.request_origin(policy, origin), origin, policy)


if __name__ == "__main__":
    unittest.main()

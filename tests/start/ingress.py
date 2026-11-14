"""A stand-in for Home Assistant's Ingress and the Supervisor, for the start test (D14).

  ingress.py supervisor   in a container at 172.30.32.2, alias `supervisor`: answers
                          GET /addons/self/info on port 80 (what run.py asks, D10),
                          and relays Ingress on port 8099
  ingress.py proxy        Ingress only, on port 8099; run on the Docker host, it
                          reaches the app from the gateway of the network,
                          172.30.32.1

Environment: APP_URL (http://<app address>:8000), SUPERVISOR_TOKEN (the token
the app was given), NETWORK (JSON: `null`, or {"8000/tcp": 8000} when the port
is published), LISTEN (address:port of Ingress, 0.0.0.0:8099 by default).

Ingress is relayed as Home Assistant does it, in one hop instead of two (Core,
then the Supervisor), with the header handling of both copied from their code
(Core 2026.11: homeassistant/components/hassio/ingress.py `_init_header` and
`_response_header`, homeassistant/components/http/headers.py; Supervisor
2026.11.0: supervisor/api/ingress.py `_init_header`):

- request: the browser's headers but the hop and encoding ones, Host kept;
  Core adds X-Hass-Source, X-Ingress-Path, X-Forwarded-For/-Host/-Proto, the
  Supervisor the X-Remote-User-* of the signed-in user and its own peer in
  X-Forwarded-For;
- response: the app's headers but Content-Length, Content-Encoding and
  Transfer-Encoding, then Core's middleware, which **replaces**
  Referrer-Policy with `no-referrer`, and sets X-Content-Type-Options and
  X-Frame-Options, on every response, Ingress included. Under `no-referrer`, a
  browser sends `Origin: null` with the form's POST (issue #11).

Standard library only: it runs with the Python of the app's image.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

INGRESS = re.compile(r"^/api/hassio_ingress/(?P<token>[A-Za-z0-9_-]+)(?P<path>/.*)?$")
# Core: _init_header drops these, the Supervisor drops the same and its own.
REQUEST_DROPPED = {
    "content-length",
    "content-encoding",
    "transfer-encoding",
    "accept-encoding",
    "sec-websocket-extensions",
    "sec-websocket-protocol",
    "sec-websocket-version",
    "sec-websocket-key",
    "x-supervisor-token",
    "x-hassio-key",
    "x-remote-user-id",
    "x-remote-user-name",
    "x-remote-user-display-name",
    "x-remote-user-groups",
    # hop by hop, set again by the client of each hop
    "connection",
    "keep-alive",
}
RESPONSE_DROPPED = {"transfer-encoding", "content-length", "content-encoding", "connection", "keep-alive"}
# homeassistant/components/http/headers.py, with use_x_frame_options (the default).
CORE_RESPONSE_HEADERS = {
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
}
# The address Core reaches the Supervisor from (Core runs on the host network).
CORE_ADDRESS = "172.30.32.1"


class Ingress(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = ""
    sys_version = ""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        sys.stderr.write("ingress: " + format % args + "\n")

    def do_GET(self) -> None:  # noqa: N802
        self.relay()

    def do_HEAD(self) -> None:  # noqa: N802
        self.relay()

    def do_POST(self) -> None:  # noqa: N802
        self.relay()

    def relay(self) -> None:
        url = urlsplit(self.path)
        match = INGRESS.match(url.path)
        if not match:
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers: list[tuple[str, str]] = [
            (name, value) for name, value in self.headers.items() if name.lower() not in REQUEST_DROPPED
        ]
        names = {name.lower() for name, _ in headers}

        def put(name: str, value: str) -> None:
            nonlocal headers
            headers = [(n, v) for n, v in headers if n.lower() != name.lower()] + [(name, value)]

        # Core
        put("X-Hass-Source", "core.ingress")
        put("X-Ingress-Path", f"/api/hassio_ingress/{match['token']}")
        prior = self.headers.get("X-Forwarded-For")
        peer = self.client_address[0]
        put("X-Forwarded-For", f"{prior}, {peer}" if prior else peer)
        if "x-forwarded-host" not in names:
            put("X-Forwarded-Host", self.headers.get("Host", ""))
        if "x-forwarded-proto" not in names:
            put("X-Forwarded-Proto", "http")
        # Supervisor
        put("X-Remote-User-Id", "0123456789abcdef0123456789abcdef")
        put("X-Remote-User-Name", "owner")
        put("X-Remote-User-Display-Name", "Owner")
        forwarded = dict((n.lower(), v) for n, v in headers)["x-forwarded-for"]
        put("X-Forwarded-For", f"{forwarded}, {CORE_ADDRESS}")

        app = urlsplit(os.environ["APP_URL"])
        conn = http.client.HTTPConnection(app.hostname, app.port or 80, timeout=60)
        target = (match["path"] or "/") + (f"?{url.query}" if url.query else "")
        try:
            conn.putrequest(self.command, target, skip_host=True, skip_accept_encoding=True)
            for name, value in headers:
                conn.putheader(name, value)
            if body is not None:
                conn.putheader("Content-Length", str(len(body)))
            conn.endheaders(body)
            response = conn.getresponse()
            data = response.read()
        except OSError as exc:
            self.send_error(502, f"app unreachable: {exc.__class__.__name__}")
            return
        finally:
            conn.close()
        self.send_response(response.status)
        for name, value in response.getheaders():
            if name.lower() in RESPONSE_DROPPED or name.title() in CORE_RESPONSE_HEADERS or name.lower() == "server":
                continue
            self.send_header(name, value)
        for name, value in CORE_RESPONSE_HEADERS.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)


class SelfInfo(BaseHTTPRequestHandler):
    """GET /addons/self/info, as the Supervisor answers an app with its token."""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        sys.stderr.write("supervisor: " + format % args + "\n")

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/addons/self/info":
            self.send_error(404)
            return
        if self.headers.get("Authorization") != f"Bearer {os.environ['SUPERVISOR_TOKEN']}":
            self.send_error(401)
            return
        network = json.loads(os.environ.get("NETWORK", "null"))
        body = json.dumps({"result": "ok", "data": {"slug": "housecairn", "network": network}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    role = sys.argv[1] if len(sys.argv) > 1 else ""
    if role not in ("supervisor", "proxy"):
        sys.stderr.write(__doc__ or "")
        return 2
    host, _, port = os.environ.get("LISTEN", "0.0.0.0:8099").rpartition(":")
    servers = [ThreadingHTTPServer((host, int(port)), Ingress)]
    if role == "supervisor":
        servers.append(ThreadingHTTPServer(("0.0.0.0", 80), SelfInfo))  # noqa: S104
    for server in servers[1:]:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    sys.stderr.write(f"{role}: listening\n")
    servers[0].serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())

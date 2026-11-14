"""A browser creating Housecairn's first administrator, for the start test (D14).

  first_admin.py --connect 127.0.0.1:8099 --host homeassistant.local:8123 \
      --base /api/hassio_ingress/<token> --code <first-account code> [--frame]

GET <base>/setup/, keep its cookies, then POST the form as a browser does from
that page (WHATWG Fetch, "append a request `Origin` header" and "determine
request's referrer"):

- under the page's effective referrer policy, as a browser computes it: the
  `Referrer-Policy` header of the response, replaced by the last valid
  `<meta name="referrer">` of the document (HTML Standard, the meta element's
  `name` attribute, referrer state). `no-referrer` (what Home Assistant's
  Ingress sets on the header, D14, and what a page without the meta keeps)
  sends `Origin: null` and no Referer; any other policy, for this same-origin
  POST, sends the page's origin, and the page's address as Referer;
- `Sec-Fetch-Site: same-origin`, `Sec-Fetch-Mode: navigate`, `Sec-Fetch-Dest`
  `iframe` with --frame (Home Assistant shows the app in a frame), else
  `document`.

With --expect-policy, the page must come with exactly that `Referrer-Policy`
header, else the run fails before any POST: the stand-in models Core, so one
that lost the header would test another case. The header is not the whole
story: the meta of the page may replace it, and the POST follows the effective
policy, so an app without the fix of issue #11 (a page with no meta) still
sends `Origin: null` here and is refused. The report has both policies.

First, the same POST as if another site sent it (`Sec-Fetch-Site: cross-site`,
with `Origin` that site's, then `null` as from a page in `no-referrer`), with
the page's cookie and token, the worst case: both must be refused (403). Then the real one: it must create the administrator (302 to the
instance's overview, under <base>), and the next page must open signed in.
Exit status 0 when both hold; a JSON report on standard output either way.
"""

from __future__ import annotations

import argparse
import http.client
import json
import re
import sys
from html.parser import HTMLParser
from http.cookies import SimpleCookie
from urllib.parse import urlencode, urlsplit

PASSWORD = "correct horse battery staple 9"  # noqa: S105 (a test instance)


# The values of the Referrer Policy standard; a meta with any other value is ignored.
REFERRER_POLICIES = frozenset(
    {
        "no-referrer",
        "no-referrer-when-downgrade",
        "same-origin",
        "origin",
        "strict-origin",
        "origin-when-cross-origin",
        "strict-origin-when-cross-origin",
        "unsafe-url",
    }
)


class _MetaReferrer(HTMLParser):
    """The `content` of every `<meta name="referrer">`, in document order."""

    def __init__(self) -> None:
        super().__init__()
        self.values: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "meta":
            return
        found = {name: value or "" for name, value in attrs}
        if found.get("name", "").strip().lower() == "referrer" and "content" in found:
            self.values.append(found["content"])


def meta_referrer_policy(body: str) -> str:
    """The policy the last valid `<meta name="referrer">` sets, or "" (none, or none valid).

    The element's content is compared ASCII case-insensitively, after stripping whitespace;
    a value that is not a referrer policy leaves the policy as it was.
    """
    parser = _MetaReferrer()
    parser.feed(body)
    policy = ""
    for value in parser.values:
        value = value.strip().lower()
        if value in REFERRER_POLICIES:
            policy = value
    return policy


def effective_policy(header: str, body: str) -> str:
    """What a browser applies to the document: the header's policy, replaced by the meta's."""
    return meta_referrer_policy(body) or header


def request_origin(policy: str, origin: str) -> str:
    """The `Origin` of a same-origin POST over HTTP (Fetch, "append a request `Origin` header").

    The request is neither GET nor HEAD and its mode is not cors (a form navigation), so the
    policy decides: `no-referrer` gives the opaque origin; `same-origin` and the others, for a
    request to the same origin and without an HTTPS-to-HTTP downgrade, give the origin.
    """
    return "null" if policy == "no-referrer" else origin


class Jar:
    """Cookies by name and path (RFC 6265 path match), as a browser keeps them over HTTP."""

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], str] = {}

    def store(self, headers: list[tuple[str, str]], request_path: str) -> None:
        for name, value in headers:
            if name.lower() != "set-cookie":
                continue
            cookie: SimpleCookie = SimpleCookie()
            cookie.load(value)
            for key, morsel in cookie.items():
                path = morsel["path"] or request_path.rsplit("/", 1)[0] or "/"
                if morsel["max-age"] == "0":
                    self.items.pop((key, path), None)
                else:
                    self.items[(key, path)] = morsel.value

    def header(self, path: str) -> str:
        def matches(cookie_path: str) -> bool:
            return cookie_path == "/" or path == cookie_path or path.startswith(cookie_path.rstrip("/") + "/")

        found = sorted(
            ((name, cookie_path, value) for (name, cookie_path), value in self.items.items() if matches(cookie_path)),
            key=lambda item: -len(item[1]),
        )
        return "; ".join(f"{name}={value}" for name, _, value in found)


class Browser:
    def __init__(self, connect: str, host: str, frame: bool) -> None:
        self.address, _, port = connect.rpartition(":")
        self.port = int(port)
        self.host = host
        self.origin = f"http://{host}"
        self.dest = "iframe" if frame else "document"
        self.jar = Jar()

    def request(
        self, method: str, path: str, headers: dict[str, str], body: bytes | None = None
    ) -> tuple[int, list[tuple[str, str]], bytes]:
        conn = http.client.HTTPConnection(self.address, self.port, timeout=60)
        try:
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            conn.putheader("Host", self.host)
            all_headers = {"User-Agent": "Mozilla/5.0 (start test)", "Accept": "text/html", **headers}
            cookie = self.jar.header(path)
            if cookie:
                all_headers["Cookie"] = cookie
            for name, value in all_headers.items():
                conn.putheader(name, value)
            if body is not None:
                conn.putheader("Content-Length", str(len(body)))
            conn.endheaders(body)
            response = conn.getresponse()
            data = response.read()
            headers_out = response.getheaders()
        finally:
            conn.close()
        self.jar.store(headers_out, path)
        return response.status, headers_out, data


def last(headers: list[tuple[str, str]], name: str) -> str:
    values = [value for key, value in headers if key.lower() == name.lower()]
    return values[-1] if values else ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--connect", required=True, help="address:port to connect to")
    parser.add_argument("--host", required=True, help="the host (and port) in the browser's address bar")
    parser.add_argument("--base", default="", help="the Ingress path, or empty on the port")
    parser.add_argument("--code", required=True, help="the first-account code of the app's log")
    parser.add_argument("--expect-policy", help="fail unless the Referrer-Policy header of the page is exactly this")
    parser.add_argument("--frame", action="store_true", help="the page is in Home Assistant's frame")
    args = parser.parse_args()
    browser = Browser(args.connect, args.host, args.frame)
    report: dict[str, object] = {}
    page = f"{args.base}/setup/"

    status, headers, body = browser.request(
        "GET", page, {"Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": browser.dest}
    )
    policy = last(headers, "Referrer-Policy").split(",")[-1].strip().lower()
    effective = effective_policy(policy, body.decode("utf-8", "replace"))
    report["get"] = {"status": status, "referrer_policy": policy, "effective_referrer_policy": effective}
    if args.expect_policy is not None:
        report["get"]["expected_referrer_policy"] = args.expect_policy.lower()  # type: ignore[index]
    if args.expect_policy is not None and policy != args.expect_policy.lower():
        report["error"] = (
            f"Referrer-Policy of the page: {policy or 'missing'}, expected {args.expect_policy.lower()}: "
            "the case does not reproduce the browser it stands for"
        )
        report["result"] = "FAIL"
        print(json.dumps(report, indent=1))
        return 1
    token = re.search(rb'name="csrfmiddlewaretoken" value="([^"]+)"', body)
    action = re.search(rb'<form method="post" action="([^"]+)"', body)
    if status != 200 or not token or not action:
        report["error"] = "the setup page did not open with its form"
        print(json.dumps(report, indent=1))
        return 1
    target = action.group(1).decode()
    fields = urlencode(
        {
            "csrfmiddlewaretoken": token.group(1).decode(),
            "code": args.code,
            "name": "Admin",
            "email": "admin@example.com",
            "password1": PASSWORD,
            "password2": PASSWORD,
        }
    ).encode()
    origin = {"Origin": request_origin(effective, browser.origin)}
    if effective != "no-referrer":
        origin["Referer"] = browser.origin + page
    form = {
        **origin,
        "Content-Type": "application/x-www-form-urlencoded",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Dest": browser.dest,
        "Sec-Fetch-User": "?1",
    }

    ok = True
    report["cross_site_posts"] = []
    for forged in ("https://attacker.example", "null"):
        forged_form = {k: v for k, v in form.items() if k != "Referer"}
        forged_form.update({"Origin": forged, "Sec-Fetch-Site": "cross-site"})
        status, _, _ = browser.request("POST", target, forged_form, fields)
        report["cross_site_posts"].append({"status": status, "origin": forged})  # type: ignore[union-attr]
        ok = ok and status == 403

    status, headers, _ = browser.request("POST", target, {**form, "Sec-Fetch-Site": "same-origin"}, fields)
    location = last(headers, "Location")
    report["post"] = {"status": status, "origin": origin["Origin"], "location": location}
    overview = f"{args.base}/instance/"
    if status != 302 or urlsplit(location).path != overview:
        ok = False
    else:
        status, _, body = browser.request(
            "GET", overview, {"Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": browser.dest}
        )
        report["overview"] = {"status": status}
        ok = ok and status == 200
    report["result"] = "PASS" if ok else "FAIL"
    print(json.dumps(report, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""Start HouseCairn as a Home Assistant app (docs/decisions.md, D2 and D3).

The Supervisor starts the container as root, mounts the app's private folder
on /data (created by root) and writes the options there, in
/data/options.json, readable by root only. HouseCairn itself runs as the
unprivileged user 10001 and reads environment variables. This script bridges
the two, then gets out of the way:

1. read /data/options.json and turn the options into HouseCairn's variables,
   then add those of Ingress (the path prefix from X-Ingress-Path, trusted
   from the Supervisor only, and frames of the same origin allowed); on
   `run`, ask the Supervisor whether the app's port is published on the host,
   which decides the host names HouseCairn accepts (D10);
2. give /data and what is in it to 10001:10001 (the Supervisor creates the
   folder, and restores backups, as root), except options.json;
3. drop root for good (groups, group, user) and replace itself with
   HouseCairn's own entry point, `python -m housecairn.entrypoint`, which
   creates the secret key in /data on first start, applies the migrations and
   runs the web server and the task worker.

Usage: run.py [run | healthcheck | backup | manage <command> ...]
(the arguments of HouseCairn's entry point; `run` by default). `healthcheck`
skips step 2: it runs every 30 seconds.

Only the standard library is used: this file runs with the system Python of
the image, in isolated mode (`python3 -I`), before any HouseCairn code.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import socket
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

DATA_DIR = Path("/data")
OPTIONS_FILE = DATA_DIR / "options.json"
# The user and group of HouseCairn's image (its Dockerfile).
APP_UID = 10001
APP_GID = 10001
# HouseCairn's entry point, with the Python of its virtual environment.
ENTRYPOINT = ("/app/.venv/bin/python", "-m", "housecairn.entrypoint")
# Never passed to HouseCairn: the Supervisor's API tokens and socket path
# (HouseCairn does not call the Supervisor; this script does, once, D10),
# SECRET_KEY, which HouseCairn generates once in
# /data/secret_key when the variable is unset, and a fixed path prefix, which
# would limit the cookies to a path the Ingress addresses do not share (D9).
DROPPED_VARIABLES = (
    "SUPERVISOR_TOKEN",
    "HASSIO_TOKEN",
    "SUPERVISOR_SOCKET",
    "SECRET_KEY",
    "HOUSECAIRN_URL_PREFIX",
)

# Whether the app's port is published on the host (D10). The Supervisor creates
# the container's port bindings from the app's `network` setting (`ports` of
# DockerApp, supervisor/docker/app.py) and returns the same setting in the
# app's own information, `GET /addons/self/info`, which every app may read
# without `hassio_api` (`api_bypass` in supervisor/api/middleware/security.py).
# The Supervisor is reached on its Unix socket when it mounts one
# (SUPERVISOR_SOCKET, no token: the socket names the app), else on its
# internal network with the app's token (SUPERVISOR_TOKEN).
APP_PORT = "8000/tcp"
SUPERVISOR_HOST = "supervisor"
SELF_INFO = "/addons/self/info"

# The Supervisor's address on its internal network: every Ingress request
# reaches the app from there ("Your web server only ever sees requests from
# the Supervisor, at 172.30.32.2", developer documentation, Ingress; the
# Supervisor's code: DOCKER_IPV4_NETWORK_MASK[2] in supervisor/const.py).
SUPERVISOR_ADDRESS = "172.30.32.2"
# Ingress (D9). The Supervisor serves the app under
# /api/hassio_ingress/<token>/ and names that path in X-Ingress-Path: HouseCairn
# reads it there, but only from the Supervisor, whose X-Forwarded-Proto also
# tells it whether the browser reached Home Assistant over HTTPS. From any other
# peer, such as a browser on the app's own port, HouseCairn removes these
# headers. Home Assistant shows the app in a frame of its own page, on the same
# origin: HouseCairn, which refuses every frame by default, then allows that
# origin and no other to frame it. Set last: neither an option nor a variable
# of the container changes them.
INGRESS_VARIABLES = {
    "HOUSECAIRN_URL_PREFIX_HEADER": "X-Ingress-Path",
    "HOUSECAIRN_FORWARDED_ALLOW_IPS": SUPERVISOR_ADDRESS,
    "HOUSECAIRN_BEHIND_TLS_PROXY": "true",
    "HOUSECAIRN_ALLOW_SAME_ORIGIN_FRAMING": "true",
}

LANGUAGES = ("en", "fr")
# One label of a host name: letters, digits and hyphens, not at either end.
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
# A host name or an IPv4 address, optionally with a leading dot (that domain
# and its subdomains, as in Django's ALLOWED_HOSTS), or an IPv6 address in
# brackets. Never "*" in the option: when the port is published, the
# instance must name the hosts it answers to (D10).
HOST = re.compile(rf"^(?:\.?{_LABEL}(?:\.{_LABEL})*|\[[0-9A-Fa-f:.]+\])$")
# An IANA time zone name, such as Europe/Paris or UTC. Django checks that it
# exists; this only keeps odd characters out of the environment.
TIME_ZONE = re.compile(r"^[A-Za-z0-9_+-]+(?:/[A-Za-z0-9_+-]+)*$")


class OptionError(Exception):
    """An option HouseCairn cannot start with; the message says which."""


class SupervisorError(Exception):
    """The Supervisor did not say whether the port is published; never holds its answer."""


def log(message: str) -> None:
    sys.stderr.write(f"housecairn-app: {message}\n")
    sys.stderr.flush()


def load_options(path: Path = OPTIONS_FILE) -> dict[str, Any]:
    """The options the Supervisor wrote, as a mapping."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise OptionError(
            f"{path} not found: this image is meant to be started by the Home Assistant Supervisor."
        ) from exc
    try:
        options = json.loads(raw)
    except ValueError as exc:
        raise OptionError(f"{path} is not valid JSON.") from exc
    if not isinstance(options, dict):
        raise OptionError(f"{path} does not hold a mapping of options.")
    return options


def _text(options: Mapping[str, Any], key: str) -> str:
    """An optional text option, stripped; empty when unset."""
    value = options.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise OptionError(f"option {key} must be text.")
    value = value.strip()
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise OptionError(f"option {key} contains a control character.")
    return value


def _hosts(options: Mapping[str, Any]) -> list[str]:
    """The names of allowed_hosts, checked; empty when the option is empty or unset."""
    value = options.get("allowed_hosts")
    if value is None:
        return []
    if not isinstance(value, list):
        raise OptionError("option allowed_hosts must be a list of host names.")
    hosts: list[str] = []
    for entry in value:
        if not isinstance(entry, str) or not HOST.fullmatch(entry.strip()):
            raise OptionError(
                f"option allowed_hosts: {entry!r} is not a host name or an IP address "
                "(an IPv6 address goes in brackets, such as [2001:db8::1])."
            )
        hosts.append(entry.strip())
    return hosts


def allowed_hosts(options: Mapping[str, Any], port_published: bool | None) -> str:
    """ALLOWED_HOSTS of HouseCairn, from whether the port is published (D10).

    - Port not published: HouseCairn is only reached from the Supervisor's
      internal network, in practice through ingress, where the Host header is
      whatever name the browser used for Home Assistant: every name is
      accepted (`*`) and allowed_hosts is not used.
    - Port published: anyone on the network may reach it, so it answers only
      to the names of allowed_hosts, through ingress as on the port; at least
      one is needed.
    - None, not asked (healthcheck, manage, backup): the names of the option,
      else `*`. The healthcheck only needs one name the server accepts.
    """
    hosts = _hosts(options)
    if port_published is False:
        return "*"
    if port_published and not hosts:
        raise OptionError(
            f"the port {APP_PORT} is published on the host (Network, on the Configuration tab), "
            "so Housecairn answers only to the names of allowed_hosts (Host names), and it is "
            "empty: add the names and addresses you use to reach Home Assistant and the port, "
            "such as homeassistant.local or 192.0.2.10, or remove the port number."
        )
    return ",".join(hosts) or "*"


def hosts_message(env: Mapping[str, str], port_published: bool) -> str:
    """What the log says at start about the host names accepted (D10)."""
    if not port_published:
        return (
            f"the port {APP_PORT} is not published on the host: Housecairn is reached through "
            "ingress only and accepts every host name there. Host names (allowed_hosts) is only "
            "used once the port is published."
        )
    return (
        f"the port {APP_PORT} is published on the host: through ingress and on the port, "
        "Housecairn answers only to the names of Host names (allowed_hosts): "
        f"{env['ALLOWED_HOSTS'].replace(',', ', ')}. A browser that uses another name or address "
        'gets "Bad request" (400) and this log shows "Invalid HTTP_HOST header": add that name '
        "to Host names on the Configuration tab, then restart the app."
    )


def environment_from_options(
    options: Mapping[str, Any], base: Mapping[str, str], port_published: bool | None = None
) -> dict[str, str]:
    """The environment of HouseCairn: `base`, less the dropped variables, plus the options.

    An option left empty sets nothing, so the setting keeps its default and,
    for the settings HouseCairn also offers in its interface, stays editable
    there (a variable that is set locks its field). `port_published` decides
    ALLOWED_HOSTS (`allowed_hosts`).
    """
    env = {key: value for key, value in base.items() if key not in DROPPED_VARIABLES}
    # The home of user 10001 in HouseCairn's image; root's would not be readable.
    env["HOME"] = "/nonexistent"

    env["ALLOWED_HOSTS"] = allowed_hosts(options, port_published)

    language = _text(options, "default_language")
    if language:
        if language not in LANGUAGES:
            raise OptionError(f"option default_language must be one of {', '.join(LANGUAGES)}.")
        env["HOUSECAIRN_DEFAULT_LANGUAGE"] = language

    # The time zone of the option, else the one of Home Assistant, which the
    # Supervisor passes as TZ: it decides what "today" is for the households.
    time_zone = _text(options, "time_zone") or base.get("TZ", "").strip()
    if time_zone:
        if not TIME_ZONE.fullmatch(time_zone):
            raise OptionError(f"time zone {time_zone!r} is not a name such as Europe/Paris.")
        env["TIME_ZONE"] = time_zone

    signup_open = options.get("signup_open")
    if signup_open is not None:
        if not isinstance(signup_open, bool):
            raise OptionError("option signup_open must be true or false.")
        env["HOUSECAIRN_SIGNUP_OPEN"] = "true" if signup_open else "false"

    env.update(_oidc(options))

    site_url = _site_url(options)
    if site_url:
        env["HOUSECAIRN_SITE_URL"] = site_url

    admin_email = _text(options, "bootstrap_admin_email")
    if admin_email:
        env["HOUSECAIRN_BOOTSTRAP_ADMIN_EMAIL"] = admin_email

    env.update(INGRESS_VARIABLES)
    return env


def _site_url(options: Mapping[str, Any]) -> str:
    """The public address, scheme and host only, as HouseCairn accepts it; empty when unset.

    HouseCairn builds every link meant to leave it (invitations, emails, QR
    labels, calendar feeds) on this address, never on the ingress path, which
    only opens inside Home Assistant (D9). It has no path: the app serves
    HouseCairn at the root of the port, and drops HOUSECAIRN_URL_PREFIX.
    """
    value = _text(options, "site_url")
    if not value:
        return ""
    try:
        parts = urlsplit(value)
        valid = (
            parts.scheme in ("http", "https")
            and bool(parts.hostname)
            and not parts.path.strip("/")
            and not (parts.query or parts.fragment)
            and parts.username is None
            and parts.password is None
            and (parts.port is None or parts.port > 0)
        )
    except ValueError:  # brackets that do not hold an address, a port out of range
        valid = False
    if not valid:
        raise OptionError(
            "option site_url must be an http:// or https:// address without a path, "
            "such as http://192.0.2.10:8000."
        )
    return value.rstrip("/")


def _oidc(options: Mapping[str, Any]) -> dict[str, str]:
    """Variables of the single sign-on provider, all or nothing."""
    server_url = _text(options, "oidc_server_url")
    client_id = _text(options, "oidc_client_id")
    secret = _text(options, "oidc_client_secret")
    name = _text(options, "oidc_provider_name")
    if not server_url:
        if client_id or secret or name:
            raise OptionError(
                "the single sign-on options need oidc_server_url, the address of the provider."
            )
        return {}
    if not server_url.startswith("https://"):
        raise OptionError("option oidc_server_url must be an https:// address.")
    if not client_id:
        raise OptionError("option oidc_client_id is needed with oidc_server_url.")
    env = {"OIDC_SERVER_URL": server_url, "OIDC_CLIENT_ID": client_id}
    if secret:
        env["OIDC_CLIENT_SECRET"] = secret
    if name:
        env["OIDC_PROVIDER_NAME"] = name
    return env


class _UnixConnection(http.client.HTTPConnection):
    """HTTP over the Supervisor's Unix socket."""

    def __init__(self, path: str, timeout: float) -> None:
        super().__init__(SUPERVISOR_HOST, timeout=timeout)
        self.socket_path = path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(self.socket_path)
        except OSError:
            sock.close()
            raise
        self.sock = sock


def self_info(
    base: Mapping[str, str], timeout: float, host: str = SUPERVISOR_HOST, port: int = 80
) -> Any:
    """The app's own information from the Supervisor, as parsed JSON.

    On the socket when the Supervisor mounts one, else, or if it fails, on the
    internal network with the token when there is one.
    """
    socket_path = base.get("SUPERVISOR_SOCKET", "").strip()
    token = base.get("SUPERVISOR_TOKEN", "").strip()
    if not socket_path and not token:
        raise SupervisorError("neither SUPERVISOR_SOCKET nor SUPERVISOR_TOKEN is set")
    if socket_path:
        try:
            return _get_json(_UnixConnection(socket_path, timeout), {})
        except SupervisorError:
            if not token:
                raise
    return _get_json(
        http.client.HTTPConnection(host, port, timeout=timeout),
        {"Authorization": f"Bearer {token}"},
    )


def _get_json(conn: http.client.HTTPConnection, headers: dict[str, str]) -> Any:
    headers = {"Accept": "application/json", **headers}
    try:
        conn.request("GET", SELF_INFO, headers=headers)
        response = conn.getresponse()
        body = response.read()
    except (OSError, http.client.HTTPException) as exc:
        raise SupervisorError(f"{SELF_INFO}: {exc.__class__.__name__}") from None
    finally:
        conn.close()
    # Never the body in a message: the app's information holds its options.
    if response.status != 200:
        raise SupervisorError(f"{SELF_INFO}: HTTP {response.status}")
    try:
        return json.loads(body)
    except ValueError:
        raise SupervisorError(f"{SELF_INFO}: not JSON") from None


def port_published(
    base: Mapping[str, str],
    *,
    fetch: Callable[[Mapping[str, str], float], Any] = self_info,
    attempts: int = 3,
    timeout: float = 5.0,
    pause: Callable[[float], None] = time.sleep,
) -> bool:
    """Whether the Supervisor publishes the app's port on the host (D10).

    `network` in the app's information maps each port of the container to its
    port on the host, `null` when it is not published; `network` itself is
    `null` for an app without ports. A malformed answer, or none after
    `attempts`, raises SupervisorError: the caller then answers as if the port
    were published, the stricter case.
    """
    error = SupervisorError("no attempt")
    for attempt in range(attempts):
        if attempt:
            pause(1.0)
        try:
            info = fetch(base, timeout)
        except SupervisorError as exc:
            error = exc
            continue
        data = info.get("data") if isinstance(info, dict) else None
        if not isinstance(data, dict) or "network" not in data:
            raise SupervisorError(f"{SELF_INFO}: no network in the answer")
        network = data["network"]
        if network is None:
            return False
        if not isinstance(network, dict):
            raise SupervisorError(f"{SELF_INFO}: network is not a mapping")
        host_port = network.get(APP_PORT)
        if host_port is None:
            return False
        if isinstance(host_port, bool) or not isinstance(host_port, int):
            raise SupervisorError(f"{SELF_INFO}: the host port of {APP_PORT} is not a number")
        return True
    raise error


def fix_ownership(
    data_dir: Path,
    uid: int,
    gid: int,
    skip: Sequence[Path] = (),
    chown: Callable[..., None] = os.chown,
    chmod: Callable[..., None] = os.chmod,
) -> int:
    """Give `data_dir` and everything below it to uid:gid; return how many entries changed.

    Symbolic links are changed themselves and never followed, so a link that
    HouseCairn's user left in /data cannot make root change a file elsewhere.
    `skip` (options.json) stays as the Supervisor wrote it.
    """
    skipped = {str(path) for path in skip}
    changed = 0
    top = os.lstat(data_dir)
    if (top.st_uid, top.st_gid) != (uid, gid):
        chown(data_dir, uid, gid, follow_symlinks=False)
        changed += 1
    chmod(data_dir, 0o700)
    for root, dirs, files in os.walk(data_dir, followlinks=False):
        for name in (*dirs, *files):
            path = os.path.join(root, name)
            if path in skipped:
                continue
            st = os.lstat(path)
            if (st.st_uid, st.st_gid) != (uid, gid):
                chown(path, uid, gid, follow_symlinks=False)
                changed += 1
    return changed


def drop_privileges(uid: int, gid: int) -> None:
    """Become uid:gid with no supplementary group, for good."""
    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)
    if os.getuid() != uid or os.geteuid() != uid or os.getgid() != gid:
        raise SystemExit("housecairn-app: could not drop root privileges.")
    try:
        os.setuid(0)
    except PermissionError:
        return
    raise SystemExit("housecairn-app: root privileges could be regained; refusing to start.")


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv) or ["run"]
    if os.geteuid() != 0:
        log("must start as root, to read the options and prepare /data; it then runs as 10001.")
        return 1
    published: bool | None = None
    try:
        options = load_options(OPTIONS_FILE)
        if args[0] == "run":
            try:
                published = port_published(os.environ)
            except SupervisorError as exc:
                log(
                    f"could not ask the Supervisor whether the port is published ({exc}): "
                    "answering as if it were."
                )
                published = True
        env = environment_from_options(options, os.environ, published)
    except OptionError as exc:
        log(str(exc))
        return 2
    if published is not None:
        log(hosts_message(env, published))
    if args[0] != "healthcheck":
        changed = fix_ownership(DATA_DIR, APP_UID, APP_GID, skip=[OPTIONS_FILE])
        if changed:
            log(f"gave {changed} entries of {DATA_DIR} to {APP_UID}:{APP_GID}")
    drop_privileges(APP_UID, APP_GID)
    os.execve(ENTRYPOINT[0], [*ENTRYPOINT, *args], env)
    return 1  # not reached: execve replaces this process


if __name__ == "__main__":
    sys.exit(main())

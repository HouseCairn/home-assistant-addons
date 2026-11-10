"""Start HouseCairn as a Home Assistant app (docs/decisions.md, D2 and D3).

The Supervisor starts the container as root, mounts the app's private folder
on /data (created by root) and writes the options there, in
/data/options.json, readable by root only. HouseCairn itself runs as the
unprivileged user 10001 and reads environment variables. This script bridges
the two, then gets out of the way:

1. read /data/options.json and turn the options into HouseCairn's variables,
   then add those of Ingress (the path prefix from X-Ingress-Path, trusted
   from the Supervisor only);
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

import json
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

DATA_DIR = Path("/data")
OPTIONS_FILE = DATA_DIR / "options.json"
# The user and group of HouseCairn's image (its Dockerfile).
APP_UID = 10001
APP_GID = 10001
# HouseCairn's entry point, with the Python of its virtual environment.
ENTRYPOINT = ("/app/.venv/bin/python", "-m", "housecairn.entrypoint")
# Never passed to HouseCairn: the Supervisor's API tokens (HouseCairn does not
# call the Supervisor), SECRET_KEY, which HouseCairn generates once in
# /data/secret_key when the variable is unset, and a fixed path prefix, which
# would limit the cookies to a path the Ingress addresses do not share (D9).
DROPPED_VARIABLES = ("SUPERVISOR_TOKEN", "HASSIO_TOKEN", "SECRET_KEY", "HOUSECAIRN_URL_PREFIX")

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
# headers. Set last: neither an option nor a variable of the container changes
# them.
INGRESS_VARIABLES = {
    "HOUSECAIRN_URL_PREFIX_HEADER": "X-Ingress-Path",
    "HOUSECAIRN_FORWARDED_ALLOW_IPS": SUPERVISOR_ADDRESS,
    "HOUSECAIRN_BEHIND_TLS_PROXY": "true",
}

LANGUAGES = ("en", "fr")
# One label of a host name: letters, digits and hyphens, not at either end.
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
# A host name or an IPv4 address, optionally with a leading dot (that domain
# and its subdomains, as in Django's ALLOWED_HOSTS), or an IPv6 address in
# brackets. Never "*": the instance must name the hosts it answers to.
HOST = re.compile(rf"^(?:\.?{_LABEL}(?:\.{_LABEL})*|\[[0-9A-Fa-f:.]+\])$")
# An IANA time zone name, such as Europe/Paris or UTC. Django checks that it
# exists; this only keeps odd characters out of the environment.
TIME_ZONE = re.compile(r"^[A-Za-z0-9_+-]+(?:/[A-Za-z0-9_+-]+)*$")


class OptionError(Exception):
    """An option HouseCairn cannot start with; the message says which."""


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


def _hosts(options: Mapping[str, Any]) -> str:
    value = options.get("allowed_hosts")
    if not isinstance(value, list) or not value:
        raise OptionError(
            "option allowed_hosts must list at least one host name, such as homeassistant.local."
        )
    hosts: list[str] = []
    for entry in value:
        if not isinstance(entry, str) or not HOST.fullmatch(entry.strip()):
            raise OptionError(
                f"option allowed_hosts: {entry!r} is not a host name or an IP address "
                "(an IPv6 address goes in brackets, such as [2001:db8::1])."
            )
        hosts.append(entry.strip())
    return ",".join(hosts)


def environment_from_options(
    options: Mapping[str, Any], base: Mapping[str, str]
) -> dict[str, str]:
    """The environment of HouseCairn: `base`, less the dropped variables, plus the options.

    An option left empty sets nothing, so the setting keeps its default and,
    for the settings HouseCairn also offers in its interface, stays editable
    there (a variable that is set locks its field).
    """
    env = {key: value for key, value in base.items() if key not in DROPPED_VARIABLES}
    # The home of user 10001 in HouseCairn's image; root's would not be readable.
    env["HOME"] = "/nonexistent"

    env["ALLOWED_HOSTS"] = _hosts(options)

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

    admin_email = _text(options, "bootstrap_admin_email")
    if admin_email:
        env["HOUSECAIRN_BOOTSTRAP_ADMIN_EMAIL"] = admin_email

    env.update(INGRESS_VARIABLES)
    return env


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
    try:
        env = environment_from_options(load_options(OPTIONS_FILE), os.environ)
    except OptionError as exc:
        log(str(exc))
        return 2
    if args[0] != "healthcheck":
        changed = fix_ownership(DATA_DIR, APP_UID, APP_GID, skip=[OPTIONS_FILE])
        if changed:
            log(f"gave {changed} entries of {DATA_DIR} to {APP_UID}:{APP_GID}")
    drop_privileges(APP_UID, APP_GID)
    os.execve(ENTRYPOINT[0], [*ENTRYPOINT, *args], env)
    return 1  # not reached: execve replaces this process


if __name__ == "__main__":
    sys.exit(main())

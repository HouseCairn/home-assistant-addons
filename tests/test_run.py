"""Tests of the start script of the app (housecairn/rootfs/.../run.py).

Standard library only: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import http.server
import importlib.util
import json
import os
import shutil
import socketserver
import sys
import tempfile
import threading
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "housecairn/rootfs/usr/local/lib/housecairn-app/run.py"
)
_spec = importlib.util.spec_from_file_location("housecairn_app_run", SCRIPT)
assert _spec and _spec.loader
run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run)

HOSTS = {"allowed_hosts": ["homeassistant.local"]}
INGRESS = {
    "HOUSECAIRN_URL_PREFIX_HEADER": "X-Ingress-Path",
    "HOUSECAIRN_FORWARDED_ALLOW_IPS": "172.30.32.2",
    "HOUSECAIRN_BEHIND_TLS_PROXY": "true",
    "HOUSECAIRN_ALLOW_SAME_ORIGIN_FRAMING": "true",
}


def env_of(options: dict, base: dict | None = None) -> dict[str, str]:
    return run.environment_from_options(options, base or {})


class EnvironmentTests(unittest.TestCase):
    def test_minimal_options_set_only_the_hosts_and_ingress(self) -> None:
        env = env_of(HOSTS, {"PATH": "/usr/bin"})
        self.assertEqual(
            env,
            {"PATH": "/usr/bin", "HOME": "/nonexistent", "ALLOWED_HOSTS": "homeassistant.local", **INGRESS},
        )

    def test_hosts_are_joined_and_stripped(self) -> None:
        env = env_of({"allowed_hosts": [" homeassistant.local", "192.0.2.10", "[2001:db8::1]"]})
        self.assertEqual(env["ALLOWED_HOSTS"], "homeassistant.local,192.0.2.10,[2001:db8::1]")

    def test_bad_hosts_are_refused(self) -> None:
        # Whether the port is published or not: a wrong entry is a mistake to show.
        for published in (None, False, True):
            for hosts in (["*"], ["home assistant"], ["a,b"], ["-bad.example.com"], [3], "a"):
                with self.subTest(published=published, hosts=hosts), self.assertRaises(run.OptionError):
                    run.environment_from_options({"allowed_hosts": hosts}, {}, published)


    def test_supervisor_tokens_and_secret_key_never_reach_the_app(self) -> None:
        base = {
            "SUPERVISOR_TOKEN": "t",
            "HASSIO_TOKEN": "t",
            "SUPERVISOR_SOCKET": "/run/supervisor/api/supervisor.sock",
            "SECRET_KEY": "k",
            "LANG": "C.UTF-8",
        }
        env = env_of(HOSTS, base)
        for name in ("SUPERVISOR_TOKEN", "HASSIO_TOKEN", "SUPERVISOR_SOCKET", "SECRET_KEY"):
            self.assertNotIn(name, env)
        self.assertEqual(env["LANG"], "C.UTF-8")

    def test_language(self) -> None:
        self.assertEqual(env_of({**HOSTS, "default_language": "fr"})["HOUSECAIRN_DEFAULT_LANGUAGE"], "fr")
        self.assertNotIn("HOUSECAIRN_DEFAULT_LANGUAGE", env_of({**HOSTS, "default_language": ""}))
        with self.assertRaises(run.OptionError):
            env_of({**HOSTS, "default_language": "de"})

    def test_time_zone_falls_back_to_home_assistant(self) -> None:
        self.assertEqual(env_of(HOSTS, {"TZ": "Europe/Paris"})["TIME_ZONE"], "Europe/Paris")
        self.assertEqual(
            env_of({**HOSTS, "time_zone": "America/New_York"}, {"TZ": "Europe/Paris"})["TIME_ZONE"],
            "America/New_York",
        )
        self.assertNotIn("TIME_ZONE", env_of(HOSTS, {}))
        with self.assertRaises(run.OptionError):
            env_of({**HOSTS, "time_zone": "Europe/Paris\nDEBUG=true"})

    def test_signup(self) -> None:
        self.assertEqual(env_of({**HOSTS, "signup_open": True})["HOUSECAIRN_SIGNUP_OPEN"], "true")
        self.assertEqual(env_of({**HOSTS, "signup_open": False})["HOUSECAIRN_SIGNUP_OPEN"], "false")
        self.assertNotIn("HOUSECAIRN_SIGNUP_OPEN", env_of(HOSTS))
        with self.assertRaises(run.OptionError):
            env_of({**HOSTS, "signup_open": "yes"})

    def test_public_address(self) -> None:
        for given, expected in (
            ("http://192.0.2.10:8000", "http://192.0.2.10:8000"),
            (" https://home.example.com/ ", "https://home.example.com"),
            ("http://[2001:db8::1]:8000", "http://[2001:db8::1]:8000"),
        ):
            with self.subTest(given=given):
                self.assertEqual(env_of({**HOSTS, "site_url": given})["HOUSECAIRN_SITE_URL"], expected)
        self.assertNotIn("HOUSECAIRN_SITE_URL", env_of(HOSTS))
        self.assertNotIn("HOUSECAIRN_SITE_URL", env_of({**HOSTS, "site_url": ""}))
        for bad in (
            "home.example.com",
            "ftp://home.example.com",
            "https://home.example.com/housecairn",
            "https://home.example.com/?a=1",
            "https://home.example.com/#top",
            "https://user:pass@home.example.com",
            "https://home.example.com:99999",
            "http://[not-an-address]",
            "https://",
            "https://home.example.com\nDEBUG=true",
            3,
        ):
            with self.subTest(bad=bad), self.assertRaises(run.OptionError):
                env_of({**HOSTS, "site_url": bad})

    def test_oidc_all_or_nothing(self) -> None:
        env = env_of(
            {
                **HOSTS,
                "oidc_server_url": "https://id.example.com",
                "oidc_client_id": "housecairn",
                "oidc_client_secret": "s",
                "oidc_provider_name": "Example SSO",
                "bootstrap_admin_email": "admin@example.com",
            }
        )
        self.assertEqual(env["OIDC_SERVER_URL"], "https://id.example.com")
        self.assertEqual(env["OIDC_CLIENT_ID"], "housecairn")
        self.assertEqual(env["OIDC_CLIENT_SECRET"], "s")
        self.assertEqual(env["OIDC_PROVIDER_NAME"], "Example SSO")
        self.assertEqual(env["HOUSECAIRN_BOOTSTRAP_ADMIN_EMAIL"], "admin@example.com")
        self.assertNotIn("OIDC_SERVER_URL", env_of(HOSTS))
        for options in (
            {"oidc_client_id": "housecairn"},
            {"oidc_server_url": "https://id.example.com"},
            {"oidc_server_url": "http://id.example.com", "oidc_client_id": "housecairn"},
        ):
            with self.subTest(options=options), self.assertRaises(run.OptionError):
                env_of({**HOSTS, **options})


class IngressTests(unittest.TestCase):
    """The prefix header of Ingress, trusted from the Supervisor and nobody else."""

    def test_prefix_comes_from_the_ingress_header(self) -> None:
        env = env_of(HOSTS)
        self.assertEqual(env["HOUSECAIRN_URL_PREFIX_HEADER"], "X-Ingress-Path")
        self.assertNotIn("HOUSECAIRN_URL_PREFIX", env)

    def test_only_the_supervisor_is_a_trusted_proxy(self) -> None:
        # Exactly one address, the Supervisor's: no network, no "*", not the
        # loopback (HouseCairn's default), not the gateway of the network.
        self.assertEqual(env_of(HOSTS)["HOUSECAIRN_FORWARDED_ALLOW_IPS"], "172.30.32.2")
        self.assertEqual(run.SUPERVISOR_ADDRESS, "172.30.32.2")

    def test_frames_of_the_same_origin_are_allowed(self) -> None:
        # Home Assistant shows Ingress in a frame of its own origin; HouseCairn
        # refuses every frame unless this is set.
        self.assertEqual(env_of(HOSTS)["HOUSECAIRN_ALLOW_SAME_ORIGIN_FRAMING"], "true")

    def test_the_container_cannot_widen_the_trust(self) -> None:
        base = {
            "HOUSECAIRN_FORWARDED_ALLOW_IPS": "*",
            "HOUSECAIRN_URL_PREFIX_HEADER": "X-Forwarded-Prefix",
            "HOUSECAIRN_BEHIND_TLS_PROXY": "false",
            "HOUSECAIRN_ALLOW_SAME_ORIGIN_FRAMING": "false",
            "HOUSECAIRN_URL_PREFIX": "/housecairn",
        }
        env = env_of(HOSTS, base)
        self.assertEqual({key: env[key] for key in INGRESS}, INGRESS)
        # A fixed prefix would limit the cookies to a path Ingress does not use.
        self.assertNotIn("HOUSECAIRN_URL_PREFIX", env)

    def test_options_cannot_reach_the_ingress_variables(self) -> None:
        options = {**HOSTS, **{key.lower(): "x" for key in INGRESS}, "HOUSECAIRN_FORWARDED_ALLOW_IPS": "*"}
        self.assertEqual({key: env_of(options)[key] for key in INGRESS}, INGRESS)


class HostNameTests(unittest.TestCase):
    """ALLOWED_HOSTS: every name through ingress alone, allowed_hosts once the port is published (D10)."""

    def test_ingress_only_accepts_every_name(self) -> None:
        for options in ({}, {"allowed_hosts": []}, {"allowed_hosts": None}, HOSTS):
            with self.subTest(options=options):
                env = run.environment_from_options(options, {}, False)
                self.assertEqual(env["ALLOWED_HOSTS"], "*")
                self.assertEqual({key: env[key] for key in INGRESS}, INGRESS)

    def test_published_port_keeps_allowed_hosts(self) -> None:
        env = run.environment_from_options({"allowed_hosts": ["homeassistant.local", "192.0.2.10"]}, {}, True)
        self.assertEqual(env["ALLOWED_HOSTS"], "homeassistant.local,192.0.2.10")
        # The trust of ingress does not change with the port.
        self.assertEqual({key: env[key] for key in INGRESS}, INGRESS)

    def test_published_port_without_allowed_hosts_is_refused_with_the_option_to_set(self) -> None:
        for options in ({}, {"allowed_hosts": []}, {"allowed_hosts": None}):
            with self.subTest(options=options):
                with self.assertRaises(run.OptionError) as caught:
                    run.environment_from_options(options, {}, True)
                message = str(caught.exception)
                self.assertIn("allowed_hosts", message)
                self.assertIn("Host names", message)
                self.assertIn("8000/tcp", message)

    def test_a_name_not_listed_is_refused_and_the_log_names_the_option(self) -> None:
        env = run.environment_from_options({"allowed_hosts": ["homeassistant.local"]}, {}, True)
        accepted = env["ALLOWED_HOSTS"].split(",")
        self.assertNotIn("*", accepted)
        self.assertNotIn("192.0.2.10", accepted)
        message = run.hosts_message(env, True)
        self.assertIn("homeassistant.local", message)
        self.assertIn("Bad request", message)
        self.assertIn("Invalid HTTP_HOST header", message)
        self.assertIn("add that name to Host names", message)
        self.assertIn("allowed_hosts", message)

    def test_ingress_only_log(self) -> None:
        message = run.hosts_message({"ALLOWED_HOSTS": "*"}, False)
        self.assertIn("not published", message)
        self.assertIn("every host name", message)

    def test_not_asked_uses_the_option_else_every_name(self) -> None:
        # healthcheck, manage, backup: no call to the Supervisor.
        self.assertEqual(env_of(HOSTS)["ALLOWED_HOSTS"], "homeassistant.local")
        self.assertEqual(env_of({})["ALLOWED_HOSTS"], "*")


def info(network: object) -> dict:
    return {"result": "ok", "data": {"slug": "housecairn", "network": network}}


class PortPublishedTests(unittest.TestCase):
    """Reading `network` of GET /addons/self/info."""

    def published(self, answer: object, **kwargs) -> bool:
        return run.port_published({}, fetch=lambda base, timeout: answer, pause=lambda s: None, **kwargs)

    def test_reads_the_host_port(self) -> None:
        self.assertTrue(self.published(info({"8000/tcp": 8000})))
        self.assertTrue(self.published(info({"8000/tcp": 18000})))
        self.assertFalse(self.published(info({"8000/tcp": None})))
        self.assertFalse(self.published(info({})))
        self.assertFalse(self.published(info(None)))

    def test_a_malformed_answer_is_an_error(self) -> None:
        for answer in (
            [],
            {"result": "ok"},
            {"result": "ok", "data": {"slug": "housecairn"}},
            info([8000]),
            info({"8000/tcp": "8000"}),
            info({"8000/tcp": True}),
        ):
            with self.subTest(answer=answer), self.assertRaises(run.SupervisorError):
                self.published(answer)

    def test_retries_then_gives_up(self) -> None:
        calls = []

        def failing(base, timeout):
            calls.append(timeout)
            raise run.SupervisorError("down")

        with self.assertRaises(run.SupervisorError):
            run.port_published({}, fetch=failing, attempts=3, pause=lambda s: None)
        self.assertEqual(len(calls), 3)

        answers = iter([run.SupervisorError("starting"), info({"8000/tcp": None})])

        def flaky(base, timeout):
            answer = next(answers)
            if isinstance(answer, Exception):
                raise answer
            return answer

        self.assertFalse(run.port_published({}, fetch=flaky, pause=lambda s: None))


class FakeSupervisor(http.server.BaseHTTPRequestHandler):
    """Answers GET /addons/self/info with the `network` of the server, as the Supervisor."""

    def do_GET(self) -> None:
        self.server.requests.append((self.path, self.headers.get("Authorization")))
        if self.path != "/addons/self/info" or (
            self.server.token and self.headers.get("Authorization") != f"Bearer {self.server.token}"
        ):
            self.send_response(403)
            self.end_headers()
            return
        body = json.dumps(info(self.server.network)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


class _UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def get_request(self):
        conn, _ = super().get_request()
        return conn, ("local", 0)


def serve(server) -> None:
    server.requests = []
    threading.Thread(target=server.serve_forever, daemon=True).start()


def unix_supervisor(path: str, network: object) -> _UnixHTTPServer:
    server = _UnixHTTPServer(path, FakeSupervisor)
    server.network, server.token = network, None
    serve(server)
    return server


class SelfInfoTests(unittest.TestCase):
    """The real HTTP exchange, on a Unix socket and over TCP with the token."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_on_the_socket_without_a_token(self) -> None:
        path = os.path.join(self.tmp.name, "supervisor.sock")
        server = unix_supervisor(path, {"8000/tcp": None})
        try:
            self.assertFalse(run.port_published({"SUPERVISOR_SOCKET": path}))
            server.network = {"8000/tcp": 8000}
            self.assertTrue(run.port_published({"SUPERVISOR_SOCKET": path}))
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(server.requests, [("/addons/self/info", None)] * 2)

    def test_over_tcp_with_the_token(self) -> None:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeSupervisor)
        server.network, server.token = {"8000/tcp": 8000}, "secret-token"
        serve(server)
        port = server.server_address[1]
        try:
            fetch = lambda base, timeout: run.self_info(base, timeout, host="127.0.0.1", port=port)
            self.assertTrue(run.port_published({"SUPERVISOR_TOKEN": "secret-token"}, fetch=fetch))
            # A refused token is an error, and its message holds neither token nor answer.
            with self.assertRaises(run.SupervisorError) as caught:
                run.port_published({"SUPERVISOR_TOKEN": "wrong"}, fetch=fetch, attempts=1)
            self.assertNotIn("wrong", str(caught.exception))
            # A socket that does not answer falls back to the token.
            base = {"SUPERVISOR_SOCKET": os.path.join(self.tmp.name, "absent.sock"), "SUPERVISOR_TOKEN": "secret-token"}
            self.assertTrue(run.port_published(base, fetch=fetch))
        finally:
            server.shutdown()
            server.server_close()

    def test_without_socket_nor_token(self) -> None:
        with self.assertRaises(run.SupervisorError):
            run.self_info({}, 1.0)


class LoadOptionsTests(unittest.TestCase):
    def test_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "options.json")
            path.write_text(json.dumps(HOSTS), encoding="utf-8")
            self.assertEqual(run.load_options(path), HOSTS)
            path.write_text("[]", encoding="utf-8")
            with self.assertRaises(run.OptionError):
                run.load_options(path)
            path.write_text("{", encoding="utf-8")
            with self.assertRaises(run.OptionError):
                run.load_options(path)
            with self.assertRaises(run.OptionError):
                run.load_options(Path(tmp, "missing.json"))


class OwnershipTests(unittest.TestCase):
    """fix_ownership with a recording chown: no privilege needed."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name, "data")
        (self.data / "media" / "photos").mkdir(parents=True)
        (self.data / "media" / "photos" / "1.jpg").write_bytes(b"x")
        (self.data / "secret_key").write_text("k\n")
        (self.data / "options.json").write_text("{}")
        self.outside = Path(self.tmp.name, "outside")
        self.outside.mkdir()
        (self.outside / "file").write_text("not ours")
        os.symlink(self.outside, self.data / "link-to-dir")
        os.symlink(self.outside / "file", self.data / "link-to-file")
        self.calls: list[tuple[str, int, int, bool]] = []

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def chown(self, path, uid, gid, *, follow_symlinks=True) -> None:
        self.calls.append((str(path), uid, gid, follow_symlinks))

    def test_everything_but_options_is_given_to_the_app_user(self) -> None:
        uid = os.getuid() + 1  # a user that owns nothing here
        changed = run.fix_ownership(
            self.data, uid, uid, skip=[self.data / "options.json"], chown=self.chown
        )
        paths = {Path(p).relative_to(self.data).as_posix() for p, *_ in self.calls}
        self.assertEqual(
            paths,
            {".", "media", "media/photos", "media/photos/1.jpg", "secret_key", "link-to-dir", "link-to-file"},
        )
        self.assertEqual(changed, len(self.calls))
        self.assertTrue(all(follow is False for *_, follow in self.calls))
        # The links are changed themselves; nothing outside /data is reached.
        self.assertFalse(any(str(self.outside) in p for p, *_ in self.calls))
        self.assertEqual(os.stat(self.data).st_mode & 0o777, 0o700)

    def test_nothing_changes_when_the_owner_is_right(self) -> None:
        changed = run.fix_ownership(
            self.data, os.getuid(), os.getgid(), skip=[self.data / "options.json"], chown=self.chown
        )
        self.assertEqual((changed, self.calls), (0, []))


DRIVER = """
import json, sys
from pathlib import Path
import importlib.util
spec = importlib.util.spec_from_file_location("run", sys.argv[1])
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)
data = Path(sys.argv[2])
run.DATA_DIR = data
run.OPTIONS_FILE = data / "options.json"
probe = "import json, os; print(json.dumps([os.getuid(), os.getgid(), os.getgroups(), sys.argv[1:], dict(os.environ)]))"
run.ENTRYPOINT = (sys.argv[3], "-I", "-c", "import sys; " + probe)
sys.exit(run.main(sys.argv[4:]))
"""


# The interpreter the probe runs with once root is dropped: the system one,
# which any user may run (a virtual environment under /root may not be).
PROBE_PYTHON = shutil.which("python3", path="/usr/bin:/bin") or sys.executable


class MainTests(unittest.TestCase):
    @unittest.skipIf(os.geteuid() == 0, "checks the refusal to start without root")
    def test_refuses_to_start_without_root(self) -> None:
        self.assertEqual(run.main(["run"]), 1)

    def start(self, options: dict, network: object = "no supervisor", env: dict | None = None, command: str = "run"):
        """Run the script as the container does, with a fake Supervisor on a socket."""
        import subprocess

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data = Path(tmp.name, "data")
        data.mkdir()
        (data / "options.json").write_text(json.dumps(options))
        os.chmod(data / "options.json", 0o600)
        (data / "db.sqlite3").write_bytes(b"")  # as restored by the Supervisor: root's
        base = {"PATH": "/usr/bin:/bin", **(env or {})}
        self.server = None
        if network != "no supervisor":
            path = os.path.join(tmp.name, "supervisor.sock")
            self.server = unix_supervisor(path, network)
            self.addCleanup(self.server.server_close)
            self.addCleanup(self.server.shutdown)
            base["SUPERVISOR_SOCKET"] = path
        out = subprocess.run(
            [sys.executable, "-I", "-c", DRIVER, str(SCRIPT), str(data), PROBE_PYTHON, command],
            env=base, capture_output=True, text=True, check=False, timeout=60,
        )
        return out, data

    @unittest.skipUnless(os.geteuid() == 0, "needs root, as in the container")
    def test_start_as_root_ends_as_the_app_user(self) -> None:
        out, data = self.start(
            {**HOSTS, "default_language": "fr"},
            network={"8000/tcp": 8000},
            env={"SUPERVISOR_TOKEN": "t", "TZ": "Europe/Paris"},
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        uid, gid, groups, args, child_env = json.loads(out.stdout)
        self.assertEqual((uid, gid, groups), (run.APP_UID, run.APP_GID, []))
        self.assertEqual(args, ["run"])
        self.assertEqual(child_env["ALLOWED_HOSTS"], "homeassistant.local")
        self.assertEqual(child_env["HOUSECAIRN_DEFAULT_LANGUAGE"], "fr")
        self.assertEqual(child_env["TIME_ZONE"], "Europe/Paris")
        for name in ("SUPERVISOR_TOKEN", "SUPERVISOR_SOCKET"):
            self.assertNotIn(name, child_env)
        self.assertEqual({key: child_env[key] for key in INGRESS}, INGRESS)
        self.assertEqual(os.stat(data).st_uid, run.APP_UID)
        self.assertEqual(os.stat(data / "db.sqlite3").st_uid, run.APP_UID)
        self.assertEqual(os.stat(data / "options.json").st_uid, 0)

    @unittest.skipUnless(os.geteuid() == 0, "needs root, as in the container")
    def test_ingress_only_start_accepts_every_name(self) -> None:
        for options in ({"allowed_hosts": []}, HOSTS):
            with self.subTest(options=options):
                out, _ = self.start(options, network={"8000/tcp": None})
                self.assertEqual(out.returncode, 0, out.stderr)
                child_env = json.loads(out.stdout)[4]
                self.assertEqual(child_env["ALLOWED_HOSTS"], "*")
                self.assertEqual({key: child_env[key] for key in INGRESS}, INGRESS)
                self.assertIn("is not published on the host", out.stderr)
                self.assertEqual(self.server.requests, [("/addons/self/info", None)])

    @unittest.skipUnless(os.geteuid() == 0, "needs root, as in the container")
    def test_published_port_start_keeps_allowed_hosts_and_names_the_option(self) -> None:
        out, _ = self.start({"allowed_hosts": ["homeassistant.local", "192.0.2.10"]}, network={"8000/tcp": 8000})
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout)[4]["ALLOWED_HOSTS"], "homeassistant.local,192.0.2.10")
        self.assertIn("homeassistant.local, 192.0.2.10", out.stderr)
        self.assertIn("add that name to Host names", out.stderr)

    @unittest.skipUnless(os.geteuid() == 0, "needs root, as in the container")
    def test_published_port_without_allowed_hosts_stops_before_anything_changes(self) -> None:
        out, data = self.start({"allowed_hosts": []}, network={"8000/tcp": 8000})
        self.assertEqual(out.returncode, 2)
        self.assertIn("allowed_hosts (Host names)", out.stderr)
        self.assertEqual(out.stdout, "")
        self.assertEqual(os.stat(data).st_uid, 0)

    @unittest.skipUnless(os.geteuid() == 0, "needs root, as in the container")
    def test_no_answer_from_the_supervisor_counts_as_a_published_port(self) -> None:
        out, _ = self.start(HOSTS)  # neither socket nor token
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout)[4]["ALLOWED_HOSTS"], "homeassistant.local")
        self.assertIn("could not ask the Supervisor", out.stderr)
        out, data = self.start({"allowed_hosts": []})
        self.assertEqual(out.returncode, 2)
        self.assertEqual(os.stat(data).st_uid, 0)

    @unittest.skipUnless(os.geteuid() == 0, "needs root, as in the container")
    def test_healthcheck_does_not_call_the_supervisor(self) -> None:
        out, data = self.start({"allowed_hosts": []}, network={"8000/tcp": 8000}, command="healthcheck")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout)[4]["ALLOWED_HOSTS"], "*")
        self.assertEqual(self.server.requests, [])
        self.assertEqual(os.stat(data).st_uid, 0)  # healthcheck leaves /data alone

    @unittest.skipUnless(os.geteuid() == 0, "needs root, as in the container")
    def test_bad_options_stop_before_anything_changes(self) -> None:
        out, data = self.start({"allowed_hosts": ["*"]}, network={"8000/tcp": None})
        self.assertEqual(out.returncode, 2)
        self.assertIn("allowed_hosts", out.stderr)
        self.assertEqual(os.stat(data).st_uid, 0)


if __name__ == "__main__":
    unittest.main()

"""Tests of the start script of the app (housecairn/rootfs/.../run.py).

Standard library only: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
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


def env_of(options: dict, base: dict | None = None) -> dict[str, str]:
    return run.environment_from_options(options, base or {})


class EnvironmentTests(unittest.TestCase):
    def test_minimal_options_set_only_the_hosts(self) -> None:
        env = env_of(HOSTS, {"PATH": "/usr/bin"})
        self.assertEqual(
            env, {"PATH": "/usr/bin", "HOME": "/nonexistent", "ALLOWED_HOSTS": "homeassistant.local"}
        )

    def test_hosts_are_joined_and_stripped(self) -> None:
        env = env_of({"allowed_hosts": [" homeassistant.local", "192.0.2.10", "[2001:db8::1]"]})
        self.assertEqual(env["ALLOWED_HOSTS"], "homeassistant.local,192.0.2.10,[2001:db8::1]")

    def test_bad_hosts_are_refused(self) -> None:
        for hosts in ([], None, ["*"], ["home assistant"], ["a,b"], ["-bad.example.com"], [3]):
            with self.subTest(hosts=hosts), self.assertRaises(run.OptionError):
                env_of({"allowed_hosts": hosts})

    def test_supervisor_tokens_and_secret_key_never_reach_the_app(self) -> None:
        base = {"SUPERVISOR_TOKEN": "t", "HASSIO_TOKEN": "t", "SECRET_KEY": "k", "LANG": "C.UTF-8"}
        env = env_of(HOSTS, base)
        for name in ("SUPERVISOR_TOKEN", "HASSIO_TOKEN", "SECRET_KEY"):
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

    @unittest.skipUnless(os.geteuid() == 0, "needs root, as in the container")
    def test_start_as_root_ends_as_the_app_user(self) -> None:
        import subprocess

        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp, "data")
            data.mkdir()
            (data / "options.json").write_text(json.dumps({**HOSTS, "default_language": "fr"}))
            os.chmod(data / "options.json", 0o600)
            (data / "db.sqlite3").write_bytes(b"")  # as restored by the Supervisor: root's
            env = {"PATH": "/usr/bin:/bin", "SUPERVISOR_TOKEN": "t", "TZ": "Europe/Paris"}
            out = subprocess.run(
                [sys.executable, "-I", "-c", DRIVER, str(SCRIPT), str(data), PROBE_PYTHON, "run"],
                env=env, capture_output=True, text=True, check=True,
            )
            uid, gid, groups, args, child_env = json.loads(out.stdout)
            self.assertEqual((uid, gid, groups), (run.APP_UID, run.APP_GID, []))
            self.assertEqual(args, ["run"])
            self.assertEqual(child_env["ALLOWED_HOSTS"], "homeassistant.local")
            self.assertEqual(child_env["HOUSECAIRN_DEFAULT_LANGUAGE"], "fr")
            self.assertEqual(child_env["TIME_ZONE"], "Europe/Paris")
            self.assertNotIn("SUPERVISOR_TOKEN", child_env)
            self.assertEqual(os.stat(data).st_uid, run.APP_UID)
            self.assertEqual(os.stat(data / "db.sqlite3").st_uid, run.APP_UID)
            self.assertEqual(os.stat(data / "options.json").st_uid, 0)

    @unittest.skipUnless(os.geteuid() == 0, "needs root, as in the container")
    def test_bad_options_stop_before_anything_changes(self) -> None:
        import subprocess

        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp, "data")
            data.mkdir()
            (data / "options.json").write_text(json.dumps({"allowed_hosts": ["*"]}))
            out = subprocess.run(
                [sys.executable, "-I", "-c", DRIVER, str(SCRIPT), str(data), PROBE_PYTHON, "run"],
                env={"PATH": "/usr/bin:/bin"}, capture_output=True, text=True, check=False,
            )
            self.assertEqual(out.returncode, 2)
            self.assertIn("allowed_hosts", out.stderr)
            self.assertEqual(os.stat(data).st_uid, 0)


if __name__ == "__main__":
    unittest.main()

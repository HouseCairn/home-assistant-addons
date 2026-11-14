"""Tests of the update of the app to a new Housecairn release (.github/scripts/app_update.py).

Standard library only, no network: python3 -m unittest discover -s tests -v
The workflow's dry run (lint.yaml, "App update (dry run)") does the same against
the real release, registry and attestations.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / ".github/scripts/app_update.py"
_spec = importlib.util.spec_from_file_location("housecairn_app_update", SCRIPT)
assert _spec and _spec.loader
update = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(update)

OLD = "sha256:" + "a" * 64
NEW = "sha256:" + "b" * 64


def release(tag: str, **extra: object) -> dict[str, object]:
    return {
        "tag_name": tag,
        "html_url": f"https://github.com/HouseCairn/housecairn/releases/tag/{tag}",
        "draft": False,
        "prerelease": False,
        **extra,
    }


class Tree:
    """A copy of the app's three files, at version 0.3.1."""

    def __init__(self, unreleased: bool = False) -> None:
        self.dir = Path(tempfile.mkdtemp())
        for name in ("Dockerfile", "config.yaml", "CHANGELOG.md"):
            shutil.copy(REPO / "housecairn" / name, self.dir / name)
        text = self.dockerfile.read_text(encoding="utf-8")
        version, digest = update.current(self.dockerfile)
        self.dockerfile.write_text(
            text.replace(f":{version}@{digest}", f":0.3.1@{OLD}"), encoding="utf-8"
        )
        config = self.config.read_text(encoding="utf-8")
        self.config.write_text(
            update.CONFIG_VERSION.sub('version: "0.3.1"', config), encoding="utf-8"
        )
        changelog = self.changelog.read_text(encoding="utf-8")
        changelog = update.UNRELEASED.sub("", changelog)
        if unreleased:
            first = update.FIRST_ENTRY.search(changelog)
            assert first
            changelog = (
                changelog[: first.start()]
                + "## Unreleased\n\n- A change of the app itself.\n\n"
                + changelog[first.start() :]
            )
        self.changelog.write_text(changelog, encoding="utf-8")

    @property
    def dockerfile(self) -> Path:
        return self.dir / "Dockerfile"

    @property
    def config(self) -> Path:
        return self.dir / "config.yaml"

    @property
    def changelog(self) -> Path:
        return self.dir / "CHANGELOG.md"

    def apply(self, version: str = "0.4.0", digest: str = NEW) -> None:
        update.apply(
            version,
            digest,
            f"https://github.com/HouseCairn/housecairn/releases/tag/v{version}",
            self.dockerfile,
            self.config,
            self.changelog,
        )

    def cleanup(self) -> None:
        shutil.rmtree(self.dir)


class CheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tree = Tree()
        self.addCleanup(self.tree.cleanup)

    def check(self, data: dict[str, object]) -> dict[str, str]:
        path = self.tree.dir / "release.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return update.check(path, self.tree.dockerfile)

    def test_the_repository_dockerfile_is_read(self) -> None:
        version, digest = update.current()
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        self.assertRegex(digest, r"^sha256:[0-9a-f]{64}$")

    def test_same_version_is_up_to_date(self) -> None:
        result = self.check(release("v0.3.1"))
        self.assertEqual((result["current"], result["latest"], result["newer"]), ("0.3.1", "0.3.1", "false"))

    def test_newer_versions(self) -> None:
        for tag in ("v0.3.2", "v0.4.0", "v1.0.0", "v0.3.10"):
            with self.subTest(tag=tag):
                result = self.check(release(tag))
                self.assertEqual(result["newer"], "true")
                self.assertEqual(result["release_url"], f"https://github.com/HouseCairn/housecairn/releases/tag/{tag}")

    def test_older_version_is_not_newer(self) -> None:
        # Compared as numbers: 0.3.1 is not newer than 0.3.10, nor 0.2.9 than 0.3.1.
        self.assertEqual(self.check(release("v0.2.9"))["newer"], "false")

    def test_refused_releases(self) -> None:
        for data in (
            release("v0.4.0", draft=True),
            release("v0.4.0", prerelease=True),
            release("0.4.0"),
            release("v0.4"),
            release("v0.4.0-rc.1"),
            release("v0.4.0", html_url="https://example.com/notes"),
        ):
            with self.subTest(data=data), self.assertRaises(update.UpdateError):
                self.check(data)

    def test_a_dockerfile_without_a_pinned_base_is_refused(self) -> None:
        self.tree.dockerfile.write_text("FROM ghcr.io/housecairn/housecairn:latest\n", encoding="utf-8")
        with self.assertRaises(update.UpdateError):
            update.current(self.tree.dockerfile)


class IndexTests(unittest.TestCase):
    def index(self, platforms: list[tuple[str, str]], media_type: str = update.INDEX_TYPES[0]) -> bytes:
        return json.dumps(
            {
                "schemaVersion": 2,
                "mediaType": media_type,
                "manifests": [
                    {"digest": "sha256:" + "c" * 64, "platform": {"os": os_, "architecture": arch}}
                    for os_, arch in platforms
                ],
            }
        ).encode()

    def test_index_with_both_platforms(self) -> None:
        body = self.index([("linux", "amd64"), ("linux", "arm64"), ("unknown", "unknown")])
        digest = "sha256:" + hashlib.sha256(body).hexdigest()
        self.assertEqual(update.check_index(body, digest, update.INDEX_TYPES[0]), digest)

    def test_digest_must_match_the_body(self) -> None:
        body = self.index([("linux", "amd64"), ("linux", "arm64")])
        with self.assertRaises(update.UpdateError):
            update.check_index(body, NEW, update.INDEX_TYPES[0])

    def test_single_platform_or_manifest_is_refused(self) -> None:
        for body in (
            self.index([("linux", "amd64")]),
            self.index([("linux", "amd64"), ("linux", "arm64")], "application/vnd.oci.image.manifest.v1+json"),
        ):
            digest = "sha256:" + hashlib.sha256(body).hexdigest()
            with self.subTest(body=body), self.assertRaises(update.UpdateError):
                update.check_index(body, digest, "")


class VerifyTests(unittest.TestCase):
    def test_identity_of_the_image_workflow(self) -> None:
        self.assertEqual(
            update.verify_command("0.4.0", NEW),
            [
                "gh", "attestation", "verify", f"oci://ghcr.io/housecairn/housecairn@{NEW}",
                "--repo", "HouseCairn/housecairn",
                "--signer-workflow", "HouseCairn/housecairn/.github/workflows/image.yml",
                "--source-ref", "refs/tags/v0.4.0",
                "--deny-self-hosted-runners",
            ],
        )  # fmt: skip

    def test_bad_arguments(self) -> None:
        for version, digest in (("0.4", NEW), ("0.4.0", "sha256:abc"), ("0.4.0", "b" * 64)):
            with self.subTest(version=version, digest=digest), self.assertRaises(update.UpdateError):
                update.verify_command(version, digest)


class ApplyTests(unittest.TestCase):
    def test_three_files_change_together(self) -> None:
        tree = Tree()
        self.addCleanup(tree.cleanup)
        before = tree.dockerfile.read_text(encoding="utf-8")
        tree.apply()
        after = tree.dockerfile.read_text(encoding="utf-8")
        self.assertEqual(update.current(tree.dockerfile), ("0.4.0", NEW))
        self.assertEqual(before.replace(f":0.3.1@{OLD}", f":0.4.0@{NEW}"), after)
        self.assertEqual(update.CONFIG_VERSION.findall(tree.config.read_text(encoding="utf-8")), ["0.4.0"])
        changelog = tree.changelog.read_text(encoding="utf-8")
        self.assertIn(
            "## 0.4.0\n\nBuilt from `ghcr.io/housecairn/housecairn:0.4.0`, a release of Housecairn. Read\n"
            "its [release notes](https://github.com/HouseCairn/housecairn/releases/tag/v0.4.0)\n",
            changelog,
        )
        self.assertLess(changelog.index("## 0.4.0"), changelog.index("## 0.3.1"))
        self.assertTrue(changelog.startswith("# Changelog\n"))

    def test_unreleased_entries_move_under_the_new_version(self) -> None:
        tree = Tree(unreleased=True)
        self.addCleanup(tree.cleanup)
        tree.apply()
        changelog = tree.changelog.read_text(encoding="utf-8")
        self.assertNotIn("## Unreleased", changelog)
        new = changelog.index("## 0.4.0")
        self.assertLess(new, changelog.index("- A change of the app itself."))
        self.assertLess(changelog.index("- A change of the app itself."), changelog.index("## 0.3.1"))

    def test_not_newer_or_bad_digest_is_refused_and_changes_nothing(self) -> None:
        tree = Tree()
        self.addCleanup(tree.cleanup)
        files = {path: path.read_text(encoding="utf-8") for path in (tree.dockerfile, tree.config, tree.changelog)}
        for version, digest in (("0.3.1", NEW), ("0.3.0", NEW), ("0.4.0", "latest")):
            with self.subTest(version=version, digest=digest), self.assertRaises(update.UpdateError):
                tree.apply(version, digest)
        for path, text in files.items():
            self.assertEqual(path.read_text(encoding="utf-8"), text)


class ScheduleStateTests(unittest.TestCase):
    """GitHub disables the cron of a public repository after 60 days without activity."""

    def state(self, state: str) -> str:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow.json"
            path.write_text(json.dumps({"state": state}), encoding="utf-8")
            return update.schedule_state("HouseCairn/home-assistant-addons", path)

    def test_an_active_workflow_is_fine(self) -> None:
        self.assertEqual(self.state("active"), "active")

    def test_a_forks_default_is_no_failure(self) -> None:
        self.assertEqual(self.state("disabled_fork"), "disabled_fork")

    def test_a_disabled_workflow_fails_visibly(self) -> None:
        for state in ("disabled_inactivity", "disabled_manually"):
            with self.subTest(state=state), self.assertRaisesRegex(update.UpdateError, state):
                self.state(state)

    def test_no_answer_is_no_failure(self) -> None:
        # No network, rate limit, or a workflow not on the default branch yet (404).
        def refuse(url: str, headers: dict[str, str]) -> tuple[bytes, object]:
            raise OSError("no answer")

        real = update._get
        update._get = refuse  # type: ignore[assignment]
        self.addCleanup(setattr, update, "_get", real)
        self.assertTrue(update.schedule_state("HouseCairn/home-assistant-addons").startswith("unknown"))


if __name__ == "__main__":
    unittest.main()

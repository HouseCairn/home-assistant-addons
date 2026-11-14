"""Keep the Housecairn app on the latest release of Housecairn (docs/decisions.md, D13).

Run by .github/workflows/app-update.yaml, and by the tests (tests/test_app_update.py).
Standard library only.

  app_update.py check [--release-json FILE]
      Compare the latest published release of HouseCairn/housecairn (public API,
      no token) with the tag in housecairn/Dockerfile. Prints a JSON object and,
      under GitHub Actions, writes the same keys to $GITHUB_OUTPUT. `--release-json`
      reads the release from a file instead of the API (tests, dry runs).
  app_update.py resolve <version>
      The digest of the multi-architecture index of
      ghcr.io/housecairn/housecairn:<version> (anonymous pull token), checked: the
      registry's digest is the SHA-256 of the index it sent, and the index holds
      linux/amd64 and linux/arm64. Prints the digest.
  app_update.py apply <version> <digest> <release url>
      Change, together (D4), the tag and digest in housecairn/Dockerfile, `version`
      in housecairn/config.yaml, and add the entry of the changelog that points to
      the release notes. Entries already under "Unreleased" move under the new
      version.

  app_update.py verify <version> <digest>
      Check the signed build provenance of that digest with `gh attestation
      verify` (Sigstore): built by the image workflow of HouseCairn/housecairn, from
      the tag v<version>, on a GitHub-hosted runner. The same identity as in the
      main repository's docs/security/verify-image.md. Needs GH_TOKEN (any token:
      the attestations of a public repository are public).
  app_update.py schedule <owner/repo> [--workflow-json FILE]
      Fail when GitHub has disabled the scheduled run of app-update.yaml (it does
      so for a public repository without activity for 60 days, and the cron then
      stops without a word). Public API, no token. A workflow that is not on the
      default branch yet, or an API that does not answer, is not a failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "housecairn" / "Dockerfile"
CONFIG = ROOT / "housecairn" / "config.yaml"
CHANGELOG = ROOT / "housecairn" / "CHANGELOG.md"

APP_REPOSITORY = "HouseCairn/housecairn"
IMAGE = "ghcr.io/housecairn/housecairn"
REGISTRY = "ghcr.io"
IMAGE_PATH = "housecairn/housecairn"
LATEST_RELEASE = f"https://api.github.com/repos/{APP_REPOSITORY}/releases/latest"
PLATFORMS = ("linux/amd64", "linux/arm64")
INDEX_TYPES = (
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
)
TIMEOUT = 30

VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
FROM_LINE = re.compile(
    r"^FROM ghcr\.io/housecairn/housecairn:(?P<version>\d+\.\d+\.\d+)@(?P<digest>sha256:[0-9a-f]{64})$",
    re.MULTILINE,
)
CONFIG_VERSION = re.compile(r'^version: "(?P<version>[^"]*)"$', re.MULTILINE)
UNRELEASED = re.compile(r"^## Unreleased\n", re.MULTILINE)
FIRST_ENTRY = re.compile(r"^## ", re.MULTILINE)


class UpdateError(Exception):
    """Something that must stop the update; the message says what."""


def parse_version(text: str) -> tuple[int, int, int]:
    match = VERSION.fullmatch(text)
    if not match:
        raise UpdateError(f"{text!r} is not a version X.Y.Z")
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def current(dockerfile: Path = DOCKERFILE) -> tuple[str, str]:
    """The version and digest the Dockerfile is built from."""
    matches = FROM_LINE.findall(dockerfile.read_text(encoding="utf-8"))
    if len(matches) != 1:
        raise UpdateError(f"{dockerfile}: expected one FROM {IMAGE}:X.Y.Z@sha256:<digest> line")
    version, digest = matches[0]
    return version, digest


def _get(url: str, headers: dict[str, str]) -> tuple[bytes, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "housecairn-app-update", **headers})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 (https only)
        return response.read(), response.headers


SCHEDULED_WORKFLOW = "app-update.yaml"


def schedule_state(repository: str, workflow_json: Path | None = None) -> str:
    """The state GitHub gives the scheduled workflow; raises when it is disabled.

    `disabled_inactivity` is the 60-day rule of public repositories: the cron
    stops, nothing tells anyone, and the app falls behind. `disabled_fork` is a
    fork's default and is no failure. Without an answer (no network, rate limit,
    or a workflow still to be merged: 404) there is nothing to say: the dry run
    must not turn red for an outage that is not the pull request's.
    """
    if workflow_json is not None:
        state = str(json.loads(workflow_json.read_text(encoding="utf-8")).get("state", ""))
    else:
        url = f"https://api.github.com/repos/{repository}/actions/workflows/{SCHEDULED_WORKFLOW}"
        try:
            body, _ = _get(url, {"Accept": "application/vnd.github+json"})
            state = str(json.loads(body).get("state", ""))
        except (OSError, ValueError) as exc:  # HTTPError is an OSError
            return f"unknown ({exc.__class__.__name__}: {exc})"
    if state.startswith("disabled") and state != "disabled_fork":
        raise UpdateError(
            f"GitHub has disabled the scheduled run of {SCHEDULED_WORKFLOW} ({state}): "
            "no new Housecairn release will open a pull request until it is enabled again "
            f"(Actions, App update, Enable workflow; docs/decisions.md, D13)"
        )
    return state


def latest_release(release_json: Path | None = None) -> dict[str, str]:
    """The latest published release: its version and the address of its notes.

    `releases/latest` never returns a draft or a pre-release.
    """
    if release_json is not None:
        release = json.loads(release_json.read_text(encoding="utf-8"))
    else:
        body, _ = _get(LATEST_RELEASE, {"Accept": "application/vnd.github+json"})
        release = json.loads(body)
    tag = str(release.get("tag_name", ""))
    if release.get("draft") or release.get("prerelease"):
        raise UpdateError(f"release {tag} is a draft or a pre-release")
    if not tag.startswith("v"):
        raise UpdateError(f"release tag {tag!r} is not vX.Y.Z")
    version = tag[1:]
    parse_version(version)
    url = str(release.get("html_url", ""))
    expected = f"https://github.com/{APP_REPOSITORY}/releases/tag/{tag}"
    if url != expected:
        raise UpdateError(f"release notes at {url!r}, expected {expected}")
    return {"version": version, "tag": tag, "url": url}


def check(release_json: Path | None = None, dockerfile: Path = DOCKERFILE) -> dict[str, str]:
    version, digest = current(dockerfile)
    release = latest_release(release_json)
    newer = parse_version(release["version"]) > parse_version(version)
    return {
        "current": version,
        "current_digest": digest,
        "latest": release["version"],
        "tag": release["tag"],
        "release_url": release["url"],
        "newer": "true" if newer else "false",
    }


def resolve(version: str) -> str:
    """The checked digest of the multi-architecture index of IMAGE:<version>."""
    parse_version(version)
    token_body, _ = _get(
        f"https://{REGISTRY}/token?scope=repository:{IMAGE_PATH}:pull&service={REGISTRY}", {}
    )
    token = json.loads(token_body)["token"]
    body, headers = _get(
        f"https://{REGISTRY}/v2/{IMAGE_PATH}/manifests/{version}",
        {"Authorization": f"Bearer {token}", "Accept": ", ".join(INDEX_TYPES)},
    )
    return check_index(body, headers.get("Docker-Content-Digest", ""), headers.get("Content-Type", ""))


def check_index(body: bytes, registry_digest: str, content_type: str) -> str:
    digest = "sha256:" + hashlib.sha256(body).hexdigest()
    if registry_digest != digest:
        raise UpdateError(f"the registry says {registry_digest!r}, the index it sent is {digest}")
    index = json.loads(body)
    media_type = index.get("mediaType") or content_type.partition(";")[0].strip()
    if media_type not in INDEX_TYPES:
        raise UpdateError(f"{media_type!r} is not a multi-architecture index")
    found = {
        f"{m.get('platform', {}).get('os')}/{m.get('platform', {}).get('architecture')}"
        for m in index.get("manifests", [])
    }
    missing = [platform for platform in PLATFORMS if platform not in found]
    if missing:
        raise UpdateError(f"the index has no image for {', '.join(missing)}")
    return digest


def verify_command(version: str, digest: str) -> list[str]:
    parse_version(version)
    if not DIGEST.fullmatch(digest):
        raise UpdateError(f"{digest!r} is not a sha256 digest")
    return [
        "gh",
        "attestation",
        "verify",
        f"oci://{IMAGE}@{digest}",
        "--repo",
        APP_REPOSITORY,
        "--signer-workflow",
        f"{APP_REPOSITORY}/.github/workflows/image.yml",
        "--source-ref",
        f"refs/tags/v{version}",
        "--deny-self-hosted-runners",
    ]


def verify(version: str, digest: str) -> None:
    command = verify_command(version, digest)
    print("+ " + " ".join(command), flush=True)
    if subprocess.run(command, check=False).returncode != 0:  # noqa: S603
        raise UpdateError(f"the provenance of {IMAGE}@{digest} does not verify")
    print(f"provenance verified: {IMAGE}:{version} = {digest}", flush=True)


def changelog_entry(version: str, url: str) -> str:
    return (
        f"Built from `{IMAGE}:{version}`, a release of Housecairn. Read\n"
        f"its [release notes]({url})\n"
        "before updating, and make a backup that includes the app, as for every update.\n"
    )


def apply(
    version: str,
    digest: str,
    url: str,
    dockerfile: Path = DOCKERFILE,
    config: Path = CONFIG,
    changelog: Path = CHANGELOG,
) -> None:
    parse_version(version)
    if not DIGEST.fullmatch(digest):
        raise UpdateError(f"{digest!r} is not a sha256 digest")
    old_version, _ = current(dockerfile)
    if parse_version(version) <= parse_version(old_version):
        raise UpdateError(f"{version} is not newer than {old_version}")

    text = dockerfile.read_text(encoding="utf-8")
    dockerfile.write_text(
        FROM_LINE.sub(f"FROM {IMAGE}:{version}@{digest}", text, count=1), encoding="utf-8"
    )

    text = config.read_text(encoding="utf-8")
    if len(CONFIG_VERSION.findall(text)) != 1:
        raise UpdateError(f'{config}: expected one line version: "X.Y.Z"')
    config.write_text(CONFIG_VERSION.sub(f'version: "{version}"', text, count=1), encoding="utf-8")

    text = changelog.read_text(encoding="utf-8")
    entry = changelog_entry(version, url)
    if UNRELEASED.search(text):
        # The changes of the app made since the last version ship with this one.
        text = UNRELEASED.sub(f"## {version}\n\n{entry}\n", text, count=1)
    else:
        first = FIRST_ENTRY.search(text)
        if not first:
            raise UpdateError(f"{changelog}: no entry to put the new one before")
        text = f"{text[: first.start()]}## {version}\n\n{entry}\n{text[first.start():]}"
    changelog.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_check = sub.add_parser("check")
    p_check.add_argument("--release-json", type=Path)
    p_resolve = sub.add_parser("resolve")
    p_resolve.add_argument("version")
    p_verify = sub.add_parser("verify")
    p_verify.add_argument("version")
    p_verify.add_argument("digest")
    p_schedule = sub.add_parser("schedule")
    p_schedule.add_argument("repository")
    p_schedule.add_argument("--workflow-json", type=Path)
    p_apply = sub.add_parser("apply")
    p_apply.add_argument("version")
    p_apply.add_argument("digest")
    p_apply.add_argument("url")
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            result = check(args.release_json)
            print(json.dumps(result, indent=1))
            output = os.environ.get("GITHUB_OUTPUT")
            if output:
                with open(output, "a", encoding="utf-8") as fh:
                    fh.writelines(f"{key}={value}\n" for key, value in result.items())
        elif args.command == "resolve":
            print(resolve(args.version))
        elif args.command == "verify":
            verify(args.version, args.digest)
        elif args.command == "schedule":
            print(f"{SCHEDULED_WORKFLOW}: {schedule_state(args.repository, args.workflow_json)}")
        else:
            apply(args.version, args.digest, args.url)
    except UpdateError as exc:
        print(f"app_update: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

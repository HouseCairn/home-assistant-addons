#!/usr/bin/env bash
# Dry run of the App update workflow (app-update.yaml), without opening anything.
#
# Usage: .github/scripts/app-update-dry-run.sh
#
# 0. The scheduled run of app-update.yaml: red when GitHub has disabled it (60
#    days without activity on a public repository), so that it does not stop in
#    silence. Needs GITHUB_REPOSITORY, skipped without.
# 1. The real app against the latest Housecairn release: prints whether it is
#    up to date.
# 2. A newer release, simulated: a copy of the repository moved back to
#    Housecairn 0.3.0, then the same steps as the workflow (check, resolve the
#    multi-architecture digest, verify its signed provenance, apply), and the
#    diff the pull request would hold. Needs GH_TOKEN for `gh attestation verify`.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
OLD_VERSION=0.3.0
OLD_DIGEST=sha256:e51ea5b565cb69ec4473634579647d18c26344b3baad12dfae5dbc74001cb340

if [ -n "${GITHUB_REPOSITORY:-}" ]; then
  echo "=== The scheduled run of app-update.yaml"
  python3 "$ROOT/.github/scripts/app_update.py" schedule "$GITHUB_REPOSITORY"
fi

echo "=== The app against the latest release"
python3 "$ROOT/.github/scripts/app_update.py" check

echo "=== A newer release, simulated: the app moved back to $OLD_VERSION"
SIM=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/app-update.XXXXXX")
trap 'rm -rf "$SIM"' EXIT
mkdir -p "$SIM/.github/scripts" "$SIM/housecairn"
cp "$ROOT/.github/scripts/app_update.py" "$SIM/.github/scripts/"
cp "$ROOT/housecairn/Dockerfile" "$ROOT/housecairn/config.yaml" "$ROOT/housecairn/CHANGELOG.md" "$SIM/housecairn/"
sed -i -E "s|^(FROM ghcr\.io/housecairn/housecairn:)[0-9.]+@sha256:[0-9a-f]{64}$|\1$OLD_VERSION@$OLD_DIGEST|" \
  "$SIM/housecairn/Dockerfile"
sed -i -E "s|^version: \"[^\"]*\"$|version: \"$OLD_VERSION\"|" "$SIM/housecairn/config.yaml"
# The changelog as it was then: its title, then the entries from $OLD_VERSION down.
awk -v old="## $OLD_VERSION" '
  /^## / && !seen { skip = 1; seen = 1 }
  $0 == old { skip = 0 }
  !skip
' "$ROOT/housecairn/CHANGELOG.md" >"$SIM/housecairn/CHANGELOG.md"
cp -r "$SIM/housecairn" "$SIM/before"

out=$(python3 "$SIM/.github/scripts/app_update.py" check)
echo "$out"
newer=$(echo "$out" | python3 -c 'import json, sys; print(json.load(sys.stdin)["newer"])')
latest=$(echo "$out" | python3 -c 'import json, sys; print(json.load(sys.stdin)["latest"])')
url=$(echo "$out" | python3 -c 'import json, sys; print(json.load(sys.stdin)["release_url"])')
if [ "$newer" != true ]; then
  echo "FAIL: $latest not seen as newer than $OLD_VERSION" >&2
  exit 1
fi
digest=$(python3 "$SIM/.github/scripts/app_update.py" resolve "$latest")
echo "multi-architecture index of $latest: $digest"
python3 "$SIM/.github/scripts/app_update.py" verify "$latest" "$digest"
python3 "$SIM/.github/scripts/app_update.py" apply "$latest" "$digest" "$url"
echo "=== What the pull request would change"
diff -u --label a/housecairn/Dockerfile --label b/housecairn/Dockerfile \
  "$SIM/before/Dockerfile" "$SIM/housecairn/Dockerfile" | grep -E '^[-+]' || true
diff -u --label a/housecairn/config.yaml --label b/housecairn/config.yaml \
  "$SIM/before/config.yaml" "$SIM/housecairn/config.yaml" | grep -E '^[-+]' || true
diff -u --label a/housecairn/CHANGELOG.md --label b/housecairn/CHANGELOG.md \
  "$SIM/before/CHANGELOG.md" "$SIM/housecairn/CHANGELOG.md" | grep -E '^[-+]' || true
echo "PASS: $latest detected, resolved, verified and applied."

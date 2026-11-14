#!/usr/bin/env bash
# Start test of the app (docs/decisions.md, D14), run by start-test.yaml.
#
# Usage: tests/start/start-test.sh <image of the app>
#
# Starts the app the way the Supervisor does (as root, /data with options.json
# in mode 600, the environment of config.yaml, SUPERVISOR_TOKEN, the
# Supervisor's network 172.30.32.0/23 with the app at 172.30.33.10), then, for
# each way in, creates the first administrator through the real form, as a
# browser does (tests/start/first_admin.py):
#
#   ingress    Ingress, relayed from the Supervisor's address, 172.30.32.2
#   port       the port published on the host, without Ingress
#
# Ingress is tests/start/ingress.py: Home Assistant's header handling, and
# Core's `Referrer-Policy: no-referrer` on every response, which the Ingress
# case requires of the page (--expect-policy), else it would not be testing
# the browser behaviour of issue #11. Each case starts
# from an empty /data, so the migrations run each time. It fails when the app
# does not become healthy, when a migration fails, or when the form is refused.
set -euo pipefail

IMAGE=${1:?usage: start-test.sh <image of the app>}
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
NETWORK=hc-start-hassio
APP=hc-start-app
SUPERVISOR=hc-start-supervisor
VOLUME=hc-start-data
APP_IP=172.30.33.10
TOKEN=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
INGRESS_PATH=/api/hassio_ingress/$TOKEN
SUPERVISOR_TOKEN=$(od -An -tx1 -N16 /dev/urandom | tr -d ' \n')
SUMMARY=${GITHUB_STEP_SUMMARY:-/dev/null}
FAILED=()

summary() { printf '%s\n' "$*" >>"$SUMMARY"; }
pass() { printf 'PASS: %s\n' "$*"; summary "- PASS: $*"; }
fail() {
  printf 'FAIL: %s\n' "$*" >&2
  summary "- **FAIL: ${*}**"
  echo "--- app log ---" >&2
  docker logs --tail 120 "$APP" >&2 2>&1 || true
  echo "--- Ingress log ---" >&2
  docker logs --tail 40 "$SUPERVISOR" >&2 2>&1 || true
  exit 1
}

stop_case() {
  docker rm -f "$APP" "$SUPERVISOR" >/dev/null 2>&1 || true
  docker volume rm -f "$VOLUME" >/dev/null 2>&1 || true
}
cleanup() {
  stop_case
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

# The `environment` of config.yaml, as the Supervisor passes it.
mapfile -t ENV_ARGS < <(python3 - "$ROOT/housecairn/config.yaml" <<'EOF'
import re, sys
inside = False
for line in open(sys.argv[1], encoding="utf-8"):
    if re.match(r"^environment:\s*$", line):
        inside = True
        continue
    if inside:
        m = re.match(r'^  ([A-Z0-9_]+): "(.*)"\s*$', line)
        if not m:
            if line.strip() and not line.startswith("  "):
                break
            continue
        print("-e")
        print(f"{m[1]}={m[2]}")
EOF
)
[ "${#ENV_ARGS[@]}" -gt 0 ] || fail "no environment read from config.yaml"

# The Supervisor's network: 172.30.32.0/23, gateway 172.30.32.1, the
# Supervisor at .2, apps in 172.30.33.0/24 (supervisor/const.py).
docker network create --subnet 172.30.32.0/23 --gateway 172.30.32.1 "$NETWORK" >/dev/null

summary "### Start test"

start_case() {
  local case=$1 options=$2 network=$3
  stop_case
  docker volume create "$VOLUME" >/dev/null
  # /data and options.json as the Supervisor writes them: root, mode 600.
  docker run --rm --user 0 --entrypoint /usr/local/bin/python3 -v "$VOLUME:/data" -e "OPTIONS=$options" "$IMAGE" -I -c '
import os
with open("/data/options.json", "w", encoding="utf-8") as fh:
    fh.write(os.environ["OPTIONS"])
os.chmod("/data/options.json", 0o600)
'
  # The Supervisor (its API on port 80, Ingress on 8099), from the app's image,
  # which has a Python.
  docker run -d --name "$SUPERVISOR" --network "$NETWORK" --ip 172.30.32.2 --network-alias supervisor \
    --user 0 --entrypoint /usr/local/bin/python3 -v "$HERE:/start:ro" -p 127.0.0.1:8099:8099 \
    -e "APP_URL=http://$APP_IP:8000" -e "SUPERVISOR_TOKEN=$SUPERVISOR_TOKEN" -e "NETWORK=$network" \
    "$IMAGE" -I /start/ingress.py supervisor >/dev/null
  local ports=()
  if [ "$case" = port ]; then ports=(-p 127.0.0.1:8000:8000); fi
  # The app, as the Supervisor starts it: as root (run.py drops it), with an
  # init, /tmp in memory (tmpfs: true), the Supervisor's token.
  docker run -d --name "$APP" --network "$NETWORK" --ip "$APP_IP" --init --tmpfs /tmp \
    -v "$VOLUME:/data" "${ENV_ARGS[@]}" -e TZ=Europe/Paris -e "SUPERVISOR_TOKEN=$SUPERVISOR_TOKEN" \
    "${ports[@]}" "$IMAGE" >/dev/null

  local status=
  for _ in $(seq 1 90); do
    status=$(docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' "$APP")
    case "$status" in
      "running healthy") break ;;
      running*) sleep 2 ;;
      *) fail "$case: the app stopped before it was healthy ($status)" ;;
    esac
  done
  [ "$status" = "running healthy" ] || fail "$case: the app is not healthy after 180 s ($status)"
  local log
  log=$(docker logs "$APP" 2>&1)
  grep -q "applying database migrations" <<<"$log" || fail "$case: no migration in the log"
  pass "$case: the app started, migrations applied, healthy"
}

first_admin() {
  local case=$1
  shift
  local code
  code=$(docker logs "$APP" 2>&1 | sed -n 's/^ *First-account code: \([A-Z0-9-]*\).*/\1/p' | tail -1)
  [ -n "$code" ] || fail "$case: no first-account code in the log"
  if out=$(python3 "$HERE/first_admin.py" --code "$code" "$@"); then
    echo "$out"
    pass "$case: first administrator created through the form; cross-site POSTs refused"
  else
    echo "$out"
    local log
    log=$(docker logs "$APP" 2>&1)
    grep -E "^Forbidden|CSRF" <<<"$log" >&2 || true
    # The next ways in are still tried, for a complete report.
    printf 'FAIL: %s\n' "$case: the first-administrator form did not go through as expected" >&2
    summary "- **FAIL: $case: the first-administrator form did not go through as expected**"
    FAILED+=("$case")
  fi
}

# 1. Ingress, from the Supervisor's address.
start_case ingress '{"allowed_hosts": []}' null
first_admin ingress --connect 127.0.0.1:8099 --host homeassistant.local:8123 --base "$INGRESS_PATH" --frame \
  --expect-policy no-referrer

# 2. The port published on the host, without Ingress.
start_case port '{"allowed_hosts": ["localhost"]}' '{"8000/tcp": 8000}'
first_admin port --connect 127.0.0.1:8000 --host localhost:8000

# A clean stop, within the app's `timeout` (30 s).
docker stop -t 30 "$APP" >/dev/null
code=$(docker inspect -f '{{.State.ExitCode}}' "$APP")
[ "$code" = 0 ] || fail "port: the app did not stop cleanly (exit code $code)"
pass "the app stopped cleanly"

if [ "${#FAILED[@]}" -gt 0 ]; then
  echo "FAIL: the first administrator could not be created through: ${FAILED[*]}" >&2
  exit 1
fi

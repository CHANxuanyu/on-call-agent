#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
FORCE_INSTALL=0
RUN_LINT=1
RUN_PYTEST=1
RUN_SMOKE=0

print_help() {
  cat <<'EOF'
Usage: ./scripts/test.sh [options]

Options:
  --smoke           Run HTTP smoke tests after ruff and pytest
  --smoke-only      Run HTTP smoke tests only
  --skip-lint       Skip ruff
  --skip-pytest     Skip pytest
  --host HOST       Host for temporary smoke-test server. Default: 127.0.0.1
  --port PORT       Preferred port for temporary smoke-test server. Default: 8000
  --install         Force reinstall requirements before testing
  --help            Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --smoke)
      RUN_SMOKE=1
      shift
      ;;
    --smoke-only)
      RUN_SMOKE=1
      RUN_LINT=0
      RUN_PYTEST=0
      shift
      ;;
    --skip-lint)
      RUN_LINT=0
      shift
      ;;
    --skip-pytest)
      RUN_PYTEST=0
      shift
      ;;
    --host)
      [[ $# -ge 2 ]] || die "--host requires a value"
      HOST="$2"
      shift 2
      ;;
    --port)
      [[ $# -ge 2 ]] || die "--port requires a value"
      PORT="$2"
      shift 2
      ;;
    --install)
      FORCE_INSTALL=1
      shift
      ;;
    --help|-h)
      print_help
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

cd "${PROJECT_ROOT}"

VENV_DIR="$(resolve_venv_dir)"
ensure_venv "${VENV_DIR}"
ensure_requirements_installed "${VENV_DIR}" "${FORCE_INSTALL}"
load_dotenv_if_present
ensure_default_runtime_env

PYTHON_BIN="${VENV_DIR}/bin/python"
RUFF_BIN="${VENV_DIR}/bin/ruff"
PYTEST_BIN="${VENV_DIR}/bin/pytest"
UVICORN_BIN="${VENV_DIR}/bin/uvicorn"

[[ -x "${PYTHON_BIN}" ]] || die "python is not available in ${VENV_DIR}"

if [[ "${RUN_LINT}" == "1" ]]; then
  [[ -x "${RUFF_BIN}" ]] || die "ruff is not installed in ${VENV_DIR}"
  log_info "running ruff"
  "${RUFF_BIN}" check .
fi

if [[ "${RUN_PYTEST}" == "1" ]]; then
  [[ -x "${PYTEST_BIN}" ]] || die "pytest is not installed in ${VENV_DIR}"
  log_info "running pytest"
  "${PYTEST_BIN}" -q
fi

if [[ "${RUN_SMOKE}" != "1" ]]; then
  log_info "done"
  exit 0
fi

[[ -x "${UVICORN_BIN}" ]] || die "uvicorn is not installed in ${VENV_DIR}"

SMOKE_PORT="$(find_available_port "${PYTHON_BIN}" "${HOST}" "${PORT}" 20)" || die "no free port found near ${HOST}:${PORT}"
if [[ "${SMOKE_PORT}" != "${PORT}" ]]; then
  log_warn "port ${PORT} is busy; using ${SMOKE_PORT} for smoke tests"
fi

BASE_URL="http://${HOST}:${SMOKE_PORT}"
SMOKE_LOG="${TMPDIR:-/tmp}/on-call-agent-smoke.log"
SERVER_PID=""

cleanup() {
  if [[ -n "${SERVER_PID}" ]] && kill -0 "${SERVER_PID}" 2>/dev/null; then
    kill "${SERVER_PID}" 2>/dev/null || true
    wait "${SERVER_PID}" 2>/dev/null || true
  fi
}

trap cleanup EXIT

log_info "starting temporary app for smoke tests at ${BASE_URL}"
: > "${SMOKE_LOG}"
(
  cd "${PROJECT_ROOT}"
  export PYTHONUNBUFFERED=1
  "${UVICORN_BIN}" app.main:app --host "${HOST}" --port "${SMOKE_PORT}"
) >"${SMOKE_LOG}" 2>&1 &
SERVER_PID=$!
log_info "smoke log: ${SMOKE_LOG}"

log_info "waiting for readiness"
if ! "${PYTHON_BIN}" - "${BASE_URL}" <<'PY'
import json
import sys
import time
import urllib.error
import urllib.request

base_url = sys.argv[1]
deadline = time.time() + 120
last_error = "service did not become ready"

while time.time() < deadline:
    try:
        with urllib.request.urlopen(f"{base_url}/readyz", timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
            if response.status == 200 and payload.get("ready") is True:
                raise SystemExit(0)
            last_error = f"readyz returned status={response.status} payload={payload}"
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        last_error = f"readyz returned status={exc.code} body={body}"
    except Exception as exc:
        last_error = str(exc)
    time.sleep(1)

raise SystemExit(last_error)
PY
then
  log_error "smoke server failed readiness check"
  tail -n 80 "${SMOKE_LOG}" || true
  exit 1
fi

log_info "running HTTP smoke assertions"
if ! "${PYTHON_BIN}" - "${BASE_URL}" "${API_KEY}" <<'PY'
import json
import sys
import urllib.parse
import urllib.request

base_url = sys.argv[1]
api_key = sys.argv[2]


def request_json(path: str, *, method: str = "GET", headers: dict[str, str] | None = None, body: bytes | None = None):
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=body,
        headers=headers or {},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
        return response.status, payload


status, payload = request_json("/healthz")
assert status == 200, payload
assert payload["status"] == "ok", payload

query = urllib.parse.urlencode({"q": "OOM"})
status, payload = request_json(f"/v1/search?{query}")
assert status == 200, payload
assert payload["results"], payload

query = urllib.parse.urlencode({"q": "服务器挂了"})
status, payload = request_json(f"/v2/search?{query}")
assert status == 200, payload
assert payload["results"], payload

body = json.dumps({"message": "数据库主从延迟超过30秒怎么处理？"}).encode("utf-8")
status, payload = request_json(
    "/v3/chat",
    method="POST",
    headers={
        "Content-Type": "application/json",
        "X-API-Key": api_key,
    },
    body=body,
)
assert status == 200, payload
assert payload["assistant_message"], payload
assert payload["tool_calls"], payload
assert payload["consulted_files"], payload
PY
then
  log_error "HTTP smoke assertions failed"
  tail -n 80 "${SMOKE_LOG}" || true
  exit 1
fi

log_info "smoke tests passed"

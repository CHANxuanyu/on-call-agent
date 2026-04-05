#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
RELOAD="${RELOAD:-1}"
FORCE_INSTALL=0

print_help() {
  cat <<'EOF'
Usage: ./scripts/start.sh [options]

Options:
  --host HOST       Bind host. Default: 127.0.0.1
  --port PORT       Preferred bind port. Default: 8000
  --no-reload       Start uvicorn without --reload
  --install         Force reinstall requirements before starting
  --help            Show this help message

Environment:
  API_KEY                 Defaults to dev-secret when unset
  RATE_LIMIT_PER_MIN      Defaults to 30 when unset
  OPENAI_API_KEY          Optional; enables the v3 LLM path
  VENV_DIR                Optional virtualenv path override
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
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
    --no-reload)
      RELOAD=0
      shift
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
UVICORN_BIN="${VENV_DIR}/bin/uvicorn"
[[ -x "${UVICORN_BIN}" ]] || die "uvicorn is not installed in ${VENV_DIR}"

SELECTED_PORT="$(find_available_port "${PYTHON_BIN}" "${HOST}" "${PORT}" 20)" || die "no free port found near ${HOST}:${PORT}"
if [[ "${SELECTED_PORT}" != "${PORT}" ]]; then
  log_warn "port ${PORT} is busy; using ${SELECTED_PORT} instead"
fi

log_info "project root: ${PROJECT_ROOT}"
log_info "virtualenv: ${VENV_DIR}"
log_info "starting app at http://${HOST}:${SELECTED_PORT}"

UVICORN_ARGS=(
  app.main:app
  --host "${HOST}"
  --port "${SELECTED_PORT}"
)

if [[ "${RELOAD}" == "1" ]]; then
  UVICORN_ARGS+=(--reload)
fi

exec "${UVICORN_BIN}" "${UVICORN_ARGS[@]}"


#!/usr/bin/env bash

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_VENV_DIR="${PROJECT_ROOT}/.venv"
FALLBACK_VENV_DIR="${PROJECT_ROOT}/venv"

log_info() {
  printf '[INFO] %s\n' "$*"
}

log_warn() {
  printf '[WARN] %s\n' "$*" >&2
}

log_error() {
  printf '[ERROR] %s\n' "$*" >&2
}

die() {
  log_error "$*"
  exit 1
}

resolve_venv_dir() {
  if [[ -n "${VENV_DIR:-}" ]]; then
    printf '%s\n' "${VENV_DIR}"
    return 0
  fi

  if [[ -x "${DEFAULT_VENV_DIR}/bin/python" ]]; then
    printf '%s\n' "${DEFAULT_VENV_DIR}"
    return 0
  fi

  if [[ -x "${FALLBACK_VENV_DIR}/bin/python" ]]; then
    printf '%s\n' "${FALLBACK_VENV_DIR}"
    return 0
  fi

  printf '%s\n' "${DEFAULT_VENV_DIR}"
}

ensure_venv() {
  local venv_dir="$1"

  if [[ -x "${venv_dir}/bin/python" ]]; then
    return 0
  fi

  command -v python3 >/dev/null 2>&1 || die "python3 is required to create a virtual environment"
  log_info "creating virtual environment at ${venv_dir}"
  python3 -m venv "${venv_dir}"
}

load_dotenv_if_present() {
  local dotenv_path="${PROJECT_ROOT}/.env"

  if [[ ! -f "${dotenv_path}" ]]; then
    return 0
  fi

  log_info "loading environment variables from ${dotenv_path}"
  set -a
  # shellcheck disable=SC1090
  source "${dotenv_path}"
  set +a
}

ensure_default_runtime_env() {
  if [[ -z "${API_KEY:-}" ]]; then
    export API_KEY="dev-secret"
    log_info "API_KEY was not set; defaulting to dev-secret"
  fi

  if [[ -z "${RATE_LIMIT_PER_MIN:-}" ]]; then
    export RATE_LIMIT_PER_MIN="30"
    log_info "RATE_LIMIT_PER_MIN was not set; defaulting to 30"
  fi
}

ensure_requirements_installed() {
  local venv_dir="$1"
  local force_install="${2:-0}"
  local python_bin="${venv_dir}/bin/python"

  if [[ "${force_install}" == "1" ]]; then
    log_info "force installing dependencies from requirements.txt"
    "${python_bin}" -m pip install -r "${PROJECT_ROOT}/requirements.txt"
    return 0
  fi

  if "${python_bin}" - <<'PY' >/dev/null 2>&1
import bs4
import fastapi
import html5lib
import httpx
import jinja2
import numpy
import openai
import prometheus_client
import pytest
import sentence_transformers
import uvicorn
PY
  then
    return 0
  fi

  log_info "installing dependencies from requirements.txt"
  "${python_bin}" -m pip install -r "${PROJECT_ROOT}/requirements.txt"
}

find_available_port() {
  local python_bin="$1"
  local host="$2"
  local preferred_port="$3"
  local search_window="${4:-20}"

  "${python_bin}" - "$host" "$preferred_port" "$search_window" <<'PY'
import socket
import sys

host = sys.argv[1]
preferred_port = int(sys.argv[2])
search_window = int(sys.argv[3])

for port in range(preferred_port, preferred_port + search_window + 1):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            continue
        print(port)
        raise SystemExit(0)

raise SystemExit(1)
PY
}


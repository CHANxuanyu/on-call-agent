#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${ROOT_DIR}/venv/bin/python"
UVICORN="${ROOT_DIR}/venv/bin/uvicorn"
OUTPUT_DIR="${OUTPUT_DIR:-/tmp/oncall_eval}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
BASE_URL="http://${HOST}:${PORT}"
KEEP_STRONG_RUNNING="${KEEP_STRONG_RUNNING:-0}"

BASELINE_LOG="${OUTPUT_DIR}/v2_baseline.log"
STRONG_LOG="${OUTPUT_DIR}/v2_strong.log"
BASELINE_JSONL="${OUTPUT_DIR}/v2_baseline.jsonl"
STRONG_JSONL="${OUTPUT_DIR}/v2_strong.jsonl"

CURRENT_SERVICE_PID=""
CURRENT_SERVICE_LABEL=""
ROLLBACK_PRINTED=0
SEARCH_METHOD=""

QUERIES=(
  "黑客攻击"
  "服务器挂了"
  "后端服务挂了"
  "SRE 集群故障"
  "CDN 故障"
  "OOM"
  "故障"
)

log_info() {
  printf '[INFO] %s\n' "$*"
}

log_warn() {
  printf '[WARN] %s\n' "$*" >&2
}

log_error() {
  printf '[ERROR] %s\n' "$*" >&2
}

require_file() {
  local path="$1"
  if [[ ! -e "${path}" ]]; then
    log_error "required path not found: ${path}"
    exit 1
  fi
  if [[ ! -x "${path}" ]]; then
    log_error "required path is not executable: ${path}"
    exit 1
  fi
}

clear_v2_env() {
  while IFS='=' read -r env_name _; do
    if [[ "${env_name}" == V2_* ]]; then
      unset "${env_name}"
    fi
  done < <(env)

  unset V2_SCORE_EXPERIMENT_PRESET
  unset V2_QUERY_VARIANT_MERGE_STRATEGY
  unset V2_DISPLAY_SCORE_TEMPERATURE
  unset V2_FUSION_DENSE_WEIGHT
  unset V2_FUSION_LEXICAL_WEIGHT
}

stop_current_service() {
  if [[ -n "${CURRENT_SERVICE_PID}" ]] && kill -0 "${CURRENT_SERVICE_PID}" 2>/dev/null; then
    log_info "stopping ${CURRENT_SERVICE_LABEL} service pid=${CURRENT_SERVICE_PID}"
    kill "${CURRENT_SERVICE_PID}" 2>/dev/null || true
    wait "${CURRENT_SERVICE_PID}" 2>/dev/null || true
  fi

  CURRENT_SERVICE_PID=""
  CURRENT_SERVICE_LABEL=""
}

kill_old_services() {
  mapfile -t pids < <(pgrep -f "uvicorn app.main:app" || true)
  if (( ${#pids[@]} == 0 )); then
    return
  fi

  log_info "killing old uvicorn app.main:app processes: ${pids[*]}"
  kill "${pids[@]}" 2>/dev/null || true
  sleep 1

  mapfile -t lingering_pids < <(pgrep -f "uvicorn app.main:app" || true)
  if (( ${#lingering_pids[@]} > 0 )); then
    log_warn "force killing lingering uvicorn app.main:app processes: ${lingering_pids[*]}"
    kill -9 "${lingering_pids[@]}" 2>/dev/null || true
  fi
}

print_rollback_block() {
  if [[ "${ROLLBACK_PRINTED}" == "1" ]]; then
    return
  fi

  ROLLBACK_PRINTED=1
  cat <<EOF
=== Rollback Command Block ===
cd "${ROOT_DIR}"
pkill -f "uvicorn app.main:app" || true
unset V2_SCORE_EXPERIMENT_PRESET
unset V2_QUERY_VARIANT_MERGE_STRATEGY
unset V2_DISPLAY_SCORE_TEMPERATURE
unset V2_FUSION_DENSE_WEIGHT
unset V2_FUSION_LEXICAL_WEIGHT
"${UVICORN}" app.main:app --host "${HOST}" --port "${PORT}"
=== End Rollback Command Block ===
EOF
}

cleanup_on_exit() {
  local exit_code=$?

  if [[ "${KEEP_STRONG_RUNNING}" == "1" && "${CURRENT_SERVICE_LABEL}" == "strong" && "${exit_code}" == "0" ]]; then
    log_info "leaving strong service running pid=${CURRENT_SERVICE_PID}"
  else
    stop_current_service
  fi

  print_rollback_block
  exit "${exit_code}"
}

trap cleanup_on_exit EXIT

wait_for_ready() {
  local label="$1"
  local log_file="$2"

  if "${PYTHON}" - "${BASE_URL}/readyz" <<'PY'
import json
import sys
import time
import urllib.error
import urllib.request

url = sys.argv[1]
attempts = 120
delay_seconds = 1.0
last_error = ""

for attempt in range(1, attempts + 1):
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            body = response.read().decode("utf-8")
            payload = json.loads(body)
            if response.status == 200 and payload.get("ready") is True:
                print(f"ready attempt={attempt} status={response.status}")
                sys.exit(0)
            last_error = f"attempt={attempt} status={response.status} body={body}"
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        last_error = f"attempt={attempt} status={exc.code} body={body}"
    except Exception as exc:
        last_error = f"attempt={attempt} error={exc}"

    print(f"waiting {last_error}", flush=True)
    time.sleep(delay_seconds)

print(last_error, file=sys.stderr)
sys.exit(1)
PY
  then
    log_info "${label} service passed readiness check"
    return 0
  fi

  log_error "${label} service failed readiness check; tailing ${log_file}"
  tail -n 60 "${log_file}" || true
  return 1
}

start_service() {
  local label="$1"
  local log_file="$2"

  stop_current_service
  kill_old_services

  : > "${log_file}"
  log_info "starting ${label} service with ${UVICORN}"

  (
    cd "${ROOT_DIR}"
    export PYTHONUNBUFFERED=1
    "${UVICORN}" app.main:app --host "${HOST}" --port "${PORT}"
  ) >"${log_file}" 2>&1 &

  CURRENT_SERVICE_PID=$!
  CURRENT_SERVICE_LABEL="${label}"
  log_info "${label} service pid=${CURRENT_SERVICE_PID} log=${log_file}"
  wait_for_ready "${label}" "${log_file}"
}

detect_search_method() {
  SEARCH_METHOD="$("${PYTHON}" - "${BASE_URL}/openapi.json" <<'PY'
import json
import sys
import urllib.request

url = sys.argv[1]
with urllib.request.urlopen(url, timeout=3) as response:
    payload = json.loads(response.read().decode("utf-8"))

operations = payload.get("paths", {}).get("/v2/search")
if not isinstance(operations, dict):
    raise SystemExit("/v2/search was not found in openapi.json")

for candidate in ("get", "post"):
    if candidate in operations:
        print(candidate.upper())
        raise SystemExit(0)

raise SystemExit("/v2/search does not expose GET or POST in openapi.json")
PY
)"
  log_info "detected /v2/search method from openapi.json: ${SEARCH_METHOD}"
}

run_queries() {
  local label="$1"
  local output_jsonl="$2"

  rm -f "${output_jsonl}"
  log_info "running ${label} evaluation -> ${output_jsonl}"

  "${PYTHON}" - "${label}" "${SEARCH_METHOD}" "${BASE_URL}/v2/search" "${output_jsonl}" "${QUERIES[@]}" <<'PY'
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

label = sys.argv[1]
method = sys.argv[2].upper()
url = sys.argv[3]
output_path = sys.argv[4]
queries = sys.argv[5:]

def request_payload(query: str):
    headers = {"Accept": "application/json"}
    if method == "GET":
        final_url = f"{url}?{urllib.parse.urlencode({'q': query})}"
        return urllib.request.Request(final_url, headers=headers, method="GET")

    if method == "POST":
        body = json.dumps({"q": query}, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
        return urllib.request.Request(url, data=body, headers=headers, method="POST")

    raise RuntimeError(f"unsupported method: {method}")

with open(output_path, "w", encoding="utf-8") as fh:
    for query in queries:
        started_at = time.perf_counter()
        record = {
            "label": label,
            "method": method,
            "query": query,
            "ok": False,
            "status": None,
            "elapsed_ms": None,
            "payload": None,
            "error": None,
        }

        try:
            request = request_payload(query)
            with urllib.request.urlopen(request, timeout=20) as response:
                body = response.read().decode("utf-8")
                payload = json.loads(body)
                record["status"] = response.status
                record["payload"] = payload
                record["ok"] = response.status == 200 and isinstance(payload.get("results"), list)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            record["status"] = exc.code
            record["error"] = body
        except Exception as exc:
            record["error"] = str(exc)

        record["elapsed_ms"] = round((time.perf_counter() - started_at) * 1000, 2)
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")

        payload = record["payload"] if isinstance(record["payload"], dict) else {}
        results = payload.get("results") if isinstance(payload.get("results"), list) else []
        top_ids = [str(item.get("id")) for item in results[:3]]
        top_scores = [item.get("score") for item in results[:3]]
        if record["ok"]:
            print(
                f"[{label}] query={query} status={record['status']} elapsed_ms={record['elapsed_ms']} "
                f"top_ids={top_ids} top_scores={top_scores}",
                flush=True,
            )
        else:
            print(
                f"[{label}] query={query} status={record['status']} elapsed_ms={record['elapsed_ms']} "
                f"error={record['error']}",
                flush=True,
            )
PY
}

print_report() {
  "${PYTHON}" - "${SEARCH_METHOD}" "${BASELINE_JSONL}" "${STRONG_JSONL}" "${BASELINE_LOG}" "${STRONG_LOG}" <<'PY'
import json
import math
import sys
from pathlib import Path

search_method = sys.argv[1]
baseline_jsonl = Path(sys.argv[2])
strong_jsonl = Path(sys.argv[3])
baseline_log = Path(sys.argv[4])
strong_log = Path(sys.argv[5])

def load_jsonl(path: Path):
    records = []
    with path.open("r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records

def load_scoring_logs(path: Path):
    events = []
    with path.open("r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("event") == "v2_search_scoring" or payload.get("message") == "v2_search_scoring":
                events.append(payload)
    return events

def results_from_record(record):
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    results = payload.get("results")
    if isinstance(results, list):
        return results
    return []

def top_scores(results, limit=5):
    values = []
    for item in results[:limit]:
        score = item.get("score")
        if isinstance(score, (int, float)):
            values.append(round(float(score), 4))
    return values

def top_ids(results, limit=5):
    values = []
    for item in results[:limit]:
        value = item.get("id")
        if value is not None:
            values.append(str(value))
    return values

def top_gap(scores):
    if len(scores) < 2:
        return None
    return round(scores[0] - scores[1], 4)

def fmt_number(value):
    if value is None:
        return "n/a"
    return f"{value:.4f}"

def fmt_list(values):
    if not values:
        return "[]"
    return "[" + ", ".join(str(value) for value in values) + "]"

def fmt_log_event(event):
    return (
        f"preset={event.get('preset')} strategy={event.get('strategy')} "
        f"dense={event.get('dense_weight')} lexical={event.get('lexical_weight')} "
        f"temp={event.get('display_score_temperature')} qvc={event.get('query_variant_count')} "
        f"top={event.get('top_result_id')} raw_gap12={event.get('top1_top2_gap')}"
    )

baseline_records = load_jsonl(baseline_jsonl)
strong_records = load_jsonl(strong_jsonl)
baseline_by_query = {record["query"]: record for record in baseline_records}
strong_by_query = {record["query"]: record for record in strong_records}
ordered_queries = [record["query"] for record in baseline_records]

print("=== V2 Rollout Report ===")
print(f"openapi /v2/search method: {search_method}")
print()

gap_increased_count = 0

for query in ordered_queries:
    baseline_record = baseline_by_query[query]
    strong_record = strong_by_query.get(query)

    baseline_results = results_from_record(baseline_record)
    strong_results = results_from_record(strong_record or {})
    baseline_scores = top_scores(baseline_results, limit=5)
    strong_scores = top_scores(strong_results, limit=5)
    baseline_gap = top_gap(baseline_scores)
    strong_gap = top_gap(strong_scores)
    gap_delta = None
    if baseline_gap is not None and strong_gap is not None:
        gap_delta = round(strong_gap - baseline_gap, 4)
        if gap_delta > 0:
            gap_increased_count += 1

    baseline_top1 = top_ids(baseline_results, limit=1)
    strong_top1 = top_ids(strong_results, limit=1)
    baseline_top1_id = baseline_top1[0] if baseline_top1 else None
    strong_top1_id = strong_top1[0] if strong_top1 else None

    print(f"Query: {query}")
    print(f"  baseline top5 scores: {fmt_list(baseline_scores)}")
    print(f"  strong top5 scores:   {fmt_list(strong_scores)}")
    print(f"  baseline top1-top2 gap: {fmt_number(baseline_gap)}")
    print(f"  strong top1-top2 gap:   {fmt_number(strong_gap)}")
    print(f"  gap delta: {fmt_number(gap_delta)}")
    print(f"  top1 changed: {'yes' if baseline_top1_id != strong_top1_id else 'no'} ({baseline_top1_id} -> {strong_top1_id})")
    print()

baseline_success = sum(1 for record in baseline_records if record.get("ok") is True)
strong_success = sum(1 for record in strong_records if record.get("ok") is True)
baseline_failures = len(baseline_records) - baseline_success
strong_failures = len(strong_records) - strong_success

baseline_events = load_scoring_logs(baseline_log)
strong_events = load_scoring_logs(strong_log)

print("=== Summary ===")
print(f"baseline success/failure: {baseline_success}/{baseline_failures}")
print(f"strong success/failure:   {strong_success}/{strong_failures}")
print(f"queries with increased gap: {gap_increased_count}")
print()

print("=== v2_search_scoring Log Excerpts: baseline ===")
if baseline_events:
    for event in baseline_events[-5:]:
        print(fmt_log_event(event))
else:
    print("no v2_search_scoring events found")
print()

print("=== v2_search_scoring Log Excerpts: strong ===")
if strong_events:
    for event in strong_events[-5:]:
        print(fmt_log_event(event))
else:
    print("no v2_search_scoring events found")
print()

expected_dense = 0.85
expected_lexical = 0.15
expected_temp = 0.7
expected_strategy = "max_score"

strong_strategy_ok = strong_events and all(event.get("strategy") == expected_strategy for event in strong_events)
strong_temp_ok = strong_events and all(
    isinstance(event.get("display_score_temperature"), (int, float))
    and math.isclose(float(event.get("display_score_temperature")), expected_temp, rel_tol=0.0, abs_tol=1e-9)
    for event in strong_events
)
strong_weights_ok = strong_events and all(
    isinstance(event.get("dense_weight"), (int, float))
    and isinstance(event.get("lexical_weight"), (int, float))
    and math.isclose(float(event.get("dense_weight")), expected_dense, rel_tol=0.0, abs_tol=1e-9)
    and math.isclose(float(event.get("lexical_weight")), expected_lexical, rel_tol=0.0, abs_tol=1e-9)
    for event in strong_events
)
observed_query_variant_counts = sorted(
    {
        int(event.get("query_variant_count"))
        for event in strong_events
        if isinstance(event.get("query_variant_count"), int)
    }
)
strong_config_ok = bool(strong_strategy_ok and strong_temp_ok and strong_weights_ok and observed_query_variant_counts)

print("=== Strong Config Validation ===")
print(f"strategy expected={expected_strategy} observed_ok={bool(strong_strategy_ok)}")
print(f"temperature expected={expected_temp} observed_ok={bool(strong_temp_ok)}")
print(f"weights expected=({expected_dense}, {expected_lexical}) observed_ok={bool(strong_weights_ok)}")
print(f"query_variant_count observed={observed_query_variant_counts}")
print(f"strong configuration effective: {'YES' if strong_config_ok else 'NO'}")
print()

passed = (
    baseline_success == len(baseline_records)
    and strong_success == len(strong_records)
    and strong_config_ok
)
print(f"FINAL RESULT: {'PASS' if passed else 'FAIL'}")
sys.exit(0 if passed else 1)
PY
}

main() {
  require_file "${PYTHON}"
  require_file "${UVICORN}"

  kill_old_services
  rm -rf "${OUTPUT_DIR}"
  mkdir -p "${OUTPUT_DIR}"

  log_info "output directory prepared: ${OUTPUT_DIR}"
  log_info "python=${PYTHON}"
  log_info "uvicorn=${UVICORN}"

  clear_v2_env
  start_service "baseline" "${BASELINE_LOG}"
  detect_search_method
  run_queries "baseline" "${BASELINE_JSONL}"

  clear_v2_env
  export V2_SCORE_EXPERIMENT_PRESET="separation_strong"
  export V2_QUERY_VARIANT_MERGE_STRATEGY="max_score"
  export V2_DISPLAY_SCORE_TEMPERATURE="0.7"
  start_service "strong" "${STRONG_LOG}"
  run_queries "strong" "${STRONG_JSONL}"

  print_report
}

main "$@"

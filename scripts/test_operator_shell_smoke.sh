#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
PYTHON_BIN="${VENV_DIR}/bin/python"
PAYLOAD_PATH="${ROOT_DIR}/docs/examples/deployment_regression_payload.json"

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "error: expected virtualenv at ${VENV_DIR}" >&2
  exit 1
fi

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "error: expected python at ${PYTHON_BIN}" >&2
  exit 1
fi

if [[ ! -f "${PAYLOAD_PATH}" ]]; then
  echo "error: expected payload at ${PAYLOAD_PATH}" >&2
  exit 1
fi

SMOKE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/oncall-agent-shell-smoke.XXXXXX")"
CHECKPOINT_ROOT="${SMOKE_ROOT}/checkpoints"
TRANSCRIPT_ROOT="${SMOKE_ROOT}/transcripts"
HANDOFF_ROOT="${SMOKE_ROOT}/handoffs"
WORKING_MEMORY_ROOT="${SMOKE_ROOT}/working_memory"
AUTO_SAFE_SETTINGS="${SMOKE_ROOT}/auto-safe-settings.toml"

mkdir -p "${CHECKPOINT_ROOT}" "${TRANSCRIPT_ROOT}" "${HANDOFF_ROOT}" "${WORKING_MEMORY_ROOT}"

cat > "${AUTO_SAFE_SETTINGS}" <<'EOF'
[shell]
default_mode = "manual"

[autonomy.auto_safe]
enabled = true
allowed_base_urls = ["http://127.0.0.1:8001"]
EOF

cat <<EOF
Operator shell smoke assets are ready.

Smoke roots
- SMOKE_ROOT=${SMOKE_ROOT}
- CHECKPOINT_ROOT=${CHECKPOINT_ROOT}
- TRANSCRIPT_ROOT=${TRANSCRIPT_ROOT}
- HANDOFF_ROOT=${HANDOFF_ROOT}
- WORKING_MEMORY_ROOT=${WORKING_MEMORY_ROOT}
- AUTO_SAFE_SETTINGS=${AUTO_SAFE_SETTINGS}

Prerequisites
- Run this from the repository root: ${ROOT_DIR}
- Payload used for the live demo: ${PAYLOAD_PATH}
- Auto-safe defaults remain fail-closed in .oncall/settings.toml.
- The temporary auto-safe settings above enable the bounded allowlisted path without editing repo files.

How to stop or reset the demo target
- Stop it with Ctrl-C in the demo-target terminal.
- Restart '${PYTHON_BIN} -m runtime.cli run-demo-target --port 8001' to reset the service to bad_version=2.1.0.

Terminal 1: demo target
----------------------------------------
cd "${ROOT_DIR}"
source .venv/bin/activate
python -m runtime.cli run-demo-target --port 8001

Expected
- JSON or text output shows the server started on http://127.0.0.1:8001
- Leave this terminal running during each scenario

Terminal 2: semi-auto shell path
----------------------------------------
cd "${ROOT_DIR}"
source .venv/bin/activate
python -m runtime.cli shell \\
  --checkpoint-root "${CHECKPOINT_ROOT}" \\
  --transcript-root "${TRANSCRIPT_ROOT}" \\
  --handoff-root "${HANDOFF_ROOT}"

Inside the shell, run:
/mode semi-auto
/new ${PAYLOAD_PATH}
/status
/inspect session

Expected checkpoints
- The shell prints 'created new session: <generated session id>'
- /status shows mode requested=semi-auto effective=semi-auto
- current phase stops at action_stub_pending_approval
- approval shows pending for rollback_recent_deployment_candidate
- next action says to review the rollback candidate and run /approve or /deny

Optional deny path
- In the same shell, before approving:
  /deny Smoke-test denial path.
- Success: phase moves to action_stub_denied and the service version on /deployment does not change.
- Red flag: rollback executes after deny, or approval status remains pending without explanation.

Approve path
----------------------------------------
Inside a fresh semi-auto session, run:
/approve Smoke-test approval for bounded rollback.
/verify
/handoff
/status

Expected checkpoints
- current phase becomes outcome_verification_succeeded
- approval shows approved
- evidence/verifier summary mentions version 2.0.9 and healthy recovery
- handoff export reports a written artifact under ${HANDOFF_ROOT}

Optional external verification after approve
----------------------------------------
Use the generated session id from the shell:
python -m runtime.cli inspect-session <session_id> \\
  --checkpoint-root "${CHECKPOINT_ROOT}" \\
  --transcript-root "${TRANSCRIPT_ROOT}" \\
  --working-memory-root "${WORKING_MEMORY_ROOT}"

Success
- current_phase: outcome_verification_succeeded
- approval_status: approved

Fresh-session check
----------------------------------------
Back in the same shell, run:
/new ${PAYLOAD_PATH}

Expected
- A new 'created new session: <generated session id>' line appears
- The new session id is different from the earlier session id
- The shell is not silently reusing the earlier completed session
- If you explicitly want reuse, use /resume <session_id> or /new --reuse-payload-session ${PAYLOAD_PATH}

Healthy/no-action path
----------------------------------------
Immediately after the successful rollback, while the demo target is still healthy on 2.0.9, run:
/status
/new ${PAYLOAD_PATH}
/status
/inspect session

Expected
- The new session still gets a fresh session id
- The runtime does not stop at action_stub_pending_approval
- current phase is action_stub_not_actionable
- approval status is none
- the reason explains the service is already healthy / already on the known-good version
- no rollback candidate is proposed

Red flags
- hypothesis or action path claims an active deployment regression on the recovered service
- approval shows pending for a rollback candidate on healthy version 2.0.9

Auto-safe degrade path with default settings
----------------------------------------
Open a fresh shell with default settings:
python -m runtime.cli shell \\
  --checkpoint-root "${CHECKPOINT_ROOT}" \\
  --transcript-root "${TRANSCRIPT_ROOT}" \\
  --handoff-root "${HANDOFF_ROOT}"

Inside the shell:
/mode auto-safe
/new ${PAYLOAD_PATH}
/status

Expected
- If the service is already healthy, it should remain non-actionable
- If the service is back on the bad release but auto-safe is disabled, the shell degrades to semi-auto
- the downgrade reason is printed and durable

Auto-safe success path
----------------------------------------
1. Reset the demo target in Terminal 1 with Ctrl-C, then restart:
   python -m runtime.cli run-demo-target --port 8001
2. In a fresh shell terminal, run:
python -m runtime.cli shell \\
  --checkpoint-root "${CHECKPOINT_ROOT}" \\
  --transcript-root "${TRANSCRIPT_ROOT}" \\
  --handoff-root "${HANDOFF_ROOT}" \\
  --settings-path "${AUTO_SAFE_SETTINGS}"

Inside that shell:
/mode auto-safe
/new ${PAYLOAD_PATH}
/status

Expected
- Either the bounded rollback auto-executes and reaches outcome_verification_succeeded
- Or the shell degrades to semi-auto with a clear durable reason
- If it succeeds, verifier summary should show healthy recovery on 2.0.9
- If it degrades, /status and /inspect session should show requested=auto-safe effective=semi-auto with a reason

Cleanup
----------------------------------------
- The smoke artifacts live under ${SMOKE_ROOT}
- Remove them when done:
  rm -rf "${SMOKE_ROOT}"
EOF

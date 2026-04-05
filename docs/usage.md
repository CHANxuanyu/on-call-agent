# Usage Guide

This guide is the practical CLI entrypoint for operators and reviewers. The runtime now has two
honest surfaces:

- replay / inspection:
  `triage -> follow-up -> evidence -> hypothesis -> recommendation -> approval-gated action stub`
- live deployment-regression demo:
  `triage -> follow-up -> evidence -> hypothesis -> recommendation -> approval-gated action stub -> bounded rollback execution -> outcome verification`

## Setup

Install the repository in editable mode:

```bash
python -m pip install -e '.[dev]'
```

If the `oncall-agent` console script is not available in your current shell, use:

```bash
.venv/bin/python -m runtime.cli <command> ...
```

## 1. Use The Interactive Operator Shell

Launch the operator shell:

```bash
oncall-agent shell
```

Recommended shell flow for the live demo:

```text
/sessions
/mode semi-auto
/new docs/examples/deployment_regression_payload.json
/status
/why-not-auto
/approve Rollback approved for the live demo target.
/tail
/handoff
/exit
```

Session workspace commands:

- `/sessions`: list recent sessions from durable checkpoints and transcripts in compact form
- `/resume <session-id|index>`: reactivate a session directly or by the numeric index shown by
  `/sessions`
- `/status`: show the current compact operator summary, including requested/effective mode and any
  downgrade reason
- `/why-not-auto`: explain the current auto-safe eligibility, allowlist status, and any blocking
  gate
- `/tail`: show recent important activity such as checkpoint writes, verifier results, approval
  events, and rollback/outcome tool results

Mode behavior:

- `manual`: no shell-driven write execution; the session stays inspection-first until the operator
  explicitly runs `/approve`.
- `semi-auto`: the shell can drive the read-only chain to the rollback candidate and then stops at
  the approval boundary.
- `auto-safe`: the shell only auto-executes the bounded deployment-regression rollback when the
  repo-local policy explicitly enables it, the target base URL is allowlisted, the verified
  rollback candidate exists, the expected versions still match live deployment state, and no
  blocking gaps remain. Otherwise the shell degrades to `semi-auto` and records the downgrade
  reason durably in the session checkpoint.

The repository-local default lives in `.oncall/settings.toml`:

```toml
[shell]
default_mode = "manual"

[autonomy.auto_safe]
enabled = false
allowed_base_urls = ["http://127.0.0.1:8001"]
```

Those defaults fail closed. `auto-safe` will not execute anything until `enabled = true` and the
target base URL is explicitly allowlisted.

## 2. Run The Live Deployment-Regression Closed Loop

Start the local demo target in a separate shell:

```bash
oncall-agent run-demo-target --port 8001
```

The demo target exposes live `/deployment`, `/health`, `/metrics`, and `/rollback` endpoints for
exactly one service.

Start the incident from the example payload:

```bash
oncall-agent start-incident \
  --family deployment-regression \
  --payload docs/examples/deployment_regression_payload.json \
  --json
```

Expected highlights:

- `"current_phase": "action_stub_pending_approval"`
- `"approval_state": {"status": "pending", ...}`
- the session id can be reused with the existing inspection commands

Approve the bounded rollback candidate:

```bash
oncall-agent resolve-approval <session_id> --decision approve --json
```

Expected highlights:

- `"current_phase": "outcome_verification_succeeded"`
- `"approval_state": {"status": "approved", ...}`
- the rollback and post-action probe are durably recorded in the transcript

If you want to re-probe runtime state after approval, rerun:

```bash
oncall-agent verify-outcome <session_id> --json
```

## 3. List The Built-In Evals

```bash
oncall-agent list-evals
```

Current canonical scenario names:

- `incident-chain-replay-recent-deployment`
- `incident-chain-replay-insufficient-evidence`

## 4. Run A Supported-Path Eval

```bash
oncall-agent run-eval incident-chain-replay-recent-deployment \
  --output-root /tmp/oncall-agent-demo \
  --json
```

Expected highlights:

- `"path_classification": "supported"`
- `"final_stage": "action_stub"`
- `"handoff_status": "written"`

The JSON output includes:

- `"output_root"` for the generated run directory
- `"session_id"` for later inspection
- `"checkpoint_path"`, `"transcript_path"`, and `"working_memory_path"`

## 5. Run A Conservative-Path Eval

```bash
oncall-agent run-eval incident-chain-replay-insufficient-evidence \
  --output-root /tmp/oncall-agent-demo \
  --json
```

Expected highlights:

- `"path_classification": "conservative"`
- `"current_phase": "action_stub_not_actionable"`
- `"handoff_status": "written"`

## 6. Inspect A Session

Using the supported-path replay as the example:

```bash
oncall-agent inspect-session incident-chain-replay-recent-deployment-session \
  --checkpoint-root /tmp/oncall-agent-demo/<run-dir>/checkpoints \
  --transcript-root /tmp/oncall-agent-demo/<run-dir>/transcripts \
  --working-memory-root /tmp/oncall-agent-demo/<run-dir>/working_memory
```

Expected highlights:

- `current_phase`
- `approval_status`
- `transcript_event_count`
- the concrete checkpoint/transcript/working-memory paths

## 7. Inspect The Artifact Chain

```bash
oncall-agent inspect-artifacts incident-chain-replay-recent-deployment-session \
  --checkpoint-root /tmp/oncall-agent-demo/<run-dir>/checkpoints \
  --transcript-root /tmp/oncall-agent-demo/<run-dir>/transcripts \
  --working-memory-root /tmp/oncall-agent-demo/<run-dir>/working_memory
```

Expected highlights:

- one line for each stage:
  `triage`, `follow_up`, `evidence`, `hypothesis`, `recommendation`, `action_stub`,
  `action_execution`, `outcome_verification`
- each line shows the current verifier-backed state for that stage

For replay sessions, `action_execution` and `outcome_verification` stay `insufficient` because the
replay path stops at the approval boundary. For live approved sessions, those stages become
`verified`.

## 8. Inspect The Audit Trail

```bash
oncall-agent show-audit incident-chain-replay-recent-deployment-session \
  --checkpoint-root /tmp/oncall-agent-demo/<run-dir>/checkpoints \
  --transcript-root /tmp/oncall-agent-demo/<run-dir>/transcripts \
  --working-memory-root /tmp/oncall-agent-demo/<run-dir>/working_memory \
  --event-type verifier_result \
  --limit 5
```

Expected highlights:

- ordered transcript events
- step numbers and timestamps
- explicit verifier names and statuses
- approval resolution events when the live path is used

## 9. Export The Handoff Artifact

```bash
oncall-agent export-handoff incident-chain-replay-recent-deployment-session \
  --checkpoint-root /tmp/oncall-agent-demo/<run-dir>/checkpoints \
  --transcript-root /tmp/oncall-agent-demo/<run-dir>/transcripts \
  --working-memory-root /tmp/oncall-agent-demo/<run-dir>/working_memory \
  --handoff-root /tmp/oncall-agent-demo/<run-dir>/handoffs
```

Expected highlights:

- `status: written`
- `handoff_path: /tmp/oncall-agent-demo/<run-dir>/handoffs/<incident_id>.json`

## 10. Where Outputs Are Written

If you pass `--output-root`, `run-eval` creates a unique subdirectory under that root containing:

- `checkpoints/`
- `transcripts/`
- `working_memory/`
- `handoffs/`

If you do not pass `--output-root`, the default root is:

- `sessions/evals/`

The easiest way to find the generated run directory is to use `run-eval --json` and read the
`output_root` field.

For live sessions started through `start-incident`, the default roots remain:

- `sessions/checkpoints/`
- `sessions/transcripts/`
- `sessions/working_memory/`
- `sessions/handoffs/`

## Troubleshooting

### The `oncall-agent` command is not found

- Make sure you ran `python -m pip install -e '.[dev]'` in the repository.
- If you are using the project virtualenv directly, run `.venv/bin/python -m runtime.cli ...`.

### `run-eval` says `unknown eval`

- Use `oncall-agent list-evals` to see the canonical names.
- The canonical names are the hyphenated ids printed by `list-evals`.

### Canonical Names Vs Accepted Aliases

- `list-evals` prints canonical names such as
  `incident-chain-replay-recent-deployment`.
- `run-eval` also accepts the built-in underscore aliases
  `incident_chain_recent_deployment` and
  `incident_chain_insufficient_evidence`.
- Prefer the canonical hyphenated names in docs, scripts, and demos.

### The live demo target is not responding

- Make sure `oncall-agent run-demo-target --port 8001` is still running in another shell.
- Update `service_base_url` in
  `docs/examples/deployment_regression_payload.json` if you use a different host or port.

### I Cannot Tell Which Replay Directory Was Generated

- Run `run-eval --json` and read `output_root`.
- If you used a dedicated root like `/tmp/oncall-agent-demo`, the generated run directory will be
  the subdirectory named in that field.

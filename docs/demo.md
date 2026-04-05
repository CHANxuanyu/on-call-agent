# Demo Guide

This is a 5-minute CLI walkthrough for the current product slice. It uses the existing
operator-facing surface rather than pytest entrypoints so the demo matches what a reviewer can
actually run today.

For a shorter command reference, see [Usage Guide](usage.md). For a more explicit local shell
validation pass, see [Operator Shell Smoke Checklist](operator_shell_smoke_checklist.md).

Runtime shape:

- replay / pre-approval path:
  `triage -> follow-up -> evidence -> hypothesis -> recommendation -> approval-gated action stub`
- live approved deployment-regression path:
  `triage -> follow-up -> evidence -> hypothesis -> recommendation -> approval-gated action stub -> bounded rollback execution -> outcome verification`

## Setup

```bash
python -m pip install -e '.[dev]'
```

If you have not installed the console script yet, you can substitute:

```bash
.venv/bin/python -m runtime.cli <command> ...
```

## 1. Run The Live Deployment-Regression Demo

Start the local demo target in a separate terminal:

```bash
oncall-agent run-demo-target --port 8001
```

Start the live incident using the example payload:

```bash
oncall-agent start-incident \
  --family deployment-regression \
  --payload docs/examples/deployment_regression_payload.json \
  --json
```

You can drive the same flow from one operator shell:

```bash
oncall-agent shell
```

Example shell transcript:

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

That transcript is the fastest reviewer path. The smoke checklist covers the same shell surface
with extra checks for fresh-session behavior, healthy/no-action gating, and `auto-safe`.

If you want a panel-first product surface instead of the shell, start:

```bash
oncall-agent console
```

The console keeps sessions, incident detail, timeline, approval, verification, and handoff as the
main surface. The assistant pane is attached to the selected session and only explains current
runtime truth; it is not a generic chat-first agent UI.

`auto-safe` is also available in the shell, but it is fail-closed by default. It only auto-runs
the bounded rollback when `.oncall/settings.toml` enables the policy and the exact live target
base URL is allowlisted. If those checks do not pass, the session degrades to `semi-auto` and the
downgrade reason is written durably into checkpoint state.

If you start multiple shell sessions while reviewing the repo, use `/sessions` to discover the
recent durable sessions and `/resume <session-id|index>` to jump back into one without leaving the
shell. `/why-not-auto` and `/tail` give the fastest operator-facing explanation of why auto-safe
did or did not run and what the session did most recently.

Expected output highlights:

- `"current_phase": "action_stub_pending_approval"`
- `"approval_state": {"status": "pending", ...}`
- live evidence came from `/deployment`, `/health`, and `/metrics`

Approve the rollback candidate:

```bash
oncall-agent resolve-approval <session_id> --decision approve --json
```

Expected output highlights:

- `"current_phase": "outcome_verification_succeeded"`
- `"approval_state": {"status": "approved", ...}`
- the runtime executed one bounded rollback and then verified live recovery

Optional rerun:

```bash
oncall-agent verify-outcome <session_id> --json
```

This is the narrow demo-grade ops-agent path in the repository today. It is intentionally
single-scenario and locally scoped.

## 2. List The Available Replay Scenarios

```bash
oncall-agent list-evals
```

Expected output:

- `incident-chain-replay-recent-deployment`
- `incident-chain-replay-insufficient-evidence`

These are the canonical built-in names shown by the CLI. The built-in underscore aliases are still
accepted by `run-eval`, but the demo should use the canonical hyphenated names.

## 3. Run One Supported Replay Scenario

```bash
oncall-agent run-eval incident-chain-replay-recent-deployment --output-root /tmp/oncall-agent-demo
```

Expected output highlights:

- `path_classification: supported`
- `final_stage: action_stub`
- `handoff_status: written`

What this proves:

- the replay path exercises the real verifier-driven chain
- the runtime reaches an approval-gated action stub on the supported branch
- the replay output includes enough durable state for later inspection and handoff export

This command writes a unique replay directory under `/tmp/oncall-agent-demo`. In the examples
below, replace `<run-dir>` with the generated path printed in `output_root`. If you prefer a
machine-readable run summary, use `--json` on `run-eval`.

## 4. Inspect The Resulting Session

```bash
oncall-agent inspect-session incident-chain-replay-recent-deployment-session \
  --checkpoint-root /tmp/oncall-agent-demo/<run-dir>/checkpoints \
  --transcript-root /tmp/oncall-agent-demo/<run-dir>/transcripts \
  --working-memory-root /tmp/oncall-agent-demo/<run-dir>/working_memory
```

Expected output highlights:

- `current_phase: action_stub_pending_approval`
- `approval_status: pending`
- `working_memory_present: True`

This confirms the replay ended at the approval boundary rather than attempting execution.

## 5. Inspect The Artifact Chain

```bash
oncall-agent inspect-artifacts incident-chain-replay-recent-deployment-session \
  --checkpoint-root /tmp/oncall-agent-demo/<run-dir>/checkpoints \
  --transcript-root /tmp/oncall-agent-demo/<run-dir>/transcripts \
  --working-memory-root /tmp/oncall-agent-demo/<run-dir>/working_memory
```

Expected output highlights:

- `triage: verified`
- `follow_up: verified`
- `evidence: verified`
- `hypothesis: verified`
- `recommendation: verified`
- `action_stub: verified`
- `action_execution: insufficient`
- `outcome_verification: insufficient`

This is the fastest way to show verifier-backed progression through the whole implemented chain.

For live approved sessions, `action_execution` and `outcome_verification` become `verified`.

## 6. Show A Compact Audit Trail

```bash
oncall-agent show-audit incident-chain-replay-recent-deployment-session \
  --checkpoint-root /tmp/oncall-agent-demo/<run-dir>/checkpoints \
  --transcript-root /tmp/oncall-agent-demo/<run-dir>/transcripts \
  --working-memory-root /tmp/oncall-agent-demo/<run-dir>/working_memory \
  --event-type verifier_result \
  --limit 3
```

Expected output:

- the last three `verifier_result` events
- step numbers and timestamps
- explicit verifier names such as `incident_hypothesis_outcome`

This is the operator-facing proof that the chain’s later phases were verifier-backed, not just
model-generated.

## 7. Export The Handoff Artifact

```bash
oncall-agent export-handoff incident-chain-replay-recent-deployment-session \
  --checkpoint-root /tmp/oncall-agent-demo/<run-dir>/checkpoints \
  --transcript-root /tmp/oncall-agent-demo/<run-dir>/transcripts \
  --working-memory-root /tmp/oncall-agent-demo/<run-dir>/working_memory \
  --handoff-root /tmp/oncall-agent-demo/<run-dir>/handoffs
```

Expected output highlights:

- `status: written`
- `handoff_path: /tmp/oncall-agent-demo/<run-dir>/handoffs/incident-replay-1.json`
- `used_working_memory: True`

This shows the current export path:

`SessionArtifactContext -> IncidentHandoffContextAssembler -> IncidentHandoffArtifactWriter`

## Optional Conservative-Branch Replay Demo

Run:

```bash
oncall-agent run-eval incident-chain-replay-insufficient-evidence --output-root /tmp/oncall-agent-demo
```

Expected output highlights:

- `path_classification: conservative`
- `current_phase: action_stub_not_actionable`
- `handoff_status: written`

This branch is useful when you want to show that the runtime stays conservative when evidence does
not justify a stronger action candidate.

## Files To Point At During The Demo

- replay runner: `src/evals/incident_chain_replay.py`
- CLI surface: `src/runtime/cli.py`
- live incident surface: `src/runtime/live_surface.py`
- demo target: `src/runtime/demo_target.py`
- rollback execution step: `src/agent/deployment_rollback_execution.py`
- outcome verification step: `src/agent/deployment_outcome_verification.py`
- session reconstruction seam: `src/context/session_artifacts.py`
- handoff assembly: `src/context/handoff.py`
- handoff regeneration: `src/context/handoff_regeneration.py`
- replay outputs: `/tmp/oncall-agent-demo/<run-dir>/`

# Demo Guide

This is a 5-minute CLI walkthrough for the current runtime. It uses the existing operator-facing
surface rather than pytest entrypoints so the demo matches what a reviewer can actually run.

Runtime shape:

`triage -> follow-up -> evidence -> hypothesis -> recommendation -> approval-gated action stub`

## Setup

```bash
python -m pip install -e '.[dev]'
```

If you have not installed the console script yet, you can substitute:

```bash
.venv/bin/python -m runtime.cli <command> ...
```

## 1. List The Available Replay Scenarios

```bash
oncall-agent list-evals
```

Expected output:

- `incident-chain-replay-recent-deployment`
- `incident-chain-replay-insufficient-evidence`

These are the canonical built-in names shown by the CLI. The built-in underscore aliases are still
accepted by `run-eval`, but the demo should use the canonical hyphenated names.

## 2. Run One Supported Scenario

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
below, replace `<run-dir>` with the generated path printed in `output_root`.

## 3. Inspect The Resulting Session

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

## 4. Inspect The Artifact Chain

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

This is the fastest way to show verifier-backed progression through the whole implemented chain.

## 5. Show A Compact Audit Trail

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

## 6. Export The Handoff Artifact

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

## Optional Conservative-Branch Demo

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
- session reconstruction seam: `src/context/session_artifacts.py`
- handoff assembly: `src/context/handoff.py`
- handoff regeneration: `src/context/handoff_regeneration.py`
- replay outputs: `/tmp/oncall-agent-demo/<run-dir>/`

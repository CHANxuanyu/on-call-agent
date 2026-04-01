# Demo Guide

This repo has two recommended demo paths. Both use the existing replay-style eval coverage, so the
demo stays aligned with what the code actually implements.

## What To Run

Install dependencies if needed:

```bash
python -m pip install -e '.[dev]'
```

Run the supported scenario:

```bash
pytest tests/integration/test_incident_chain_replay_eval.py::test_incident_chain_replay_eval_runs_supported_hypothesis_chain
```

Run the conservative scenario:

```bash
pytest tests/integration/test_incident_chain_replay_eval.py::test_incident_chain_replay_eval_runs_insufficient_evidence_chain
```

## Scenario A: Supported Path

Fixture:
- `evals/fixtures/incident_chain_recent_deployment.json`

Artifact path to highlight:
- follow-up target: `recent_deployment`
- hypothesis: `deployment_regression`
- recommendation: `validate_recent_deployment`
- action stub: `deployment_validation_candidate`

What this proves:
- the harness can resume through multiple typed slices
- verifier-gated transitions can carry a supported incident theory forward
- stronger evidence produces an action candidate, but still behind an explicit approval gate

Artifacts to point at during the demo:
- replay runner: `src/evals/incident_chain_replay.py`
- architecture summary: `docs/architecture.md`
- integration coverage: `tests/integration/test_incident_chain_replay_eval.py`

## Scenario B: Conservative Path

Fixture:
- `evals/fixtures/incident_chain_insufficient_evidence.json`

Artifact path to highlight:
- follow-up target: `runbook`
- hypothesis: `insufficient_evidence`
- recommendation: `investigate_more`
- action stub: `no_actionable_stub_yet`

What this proves:
- the harness does not force a stronger claim than the artifact chain supports
- verifier-driven logic can preserve a conservative branch cleanly
- approval-aware design is explicit even when no actionable candidate should be created

Artifacts to point at during the demo:
- fixtures in `evals/fixtures/`
- step runners in `src/agent/`
- transcript and checkpoint contracts in `src/transcripts/` and `src/memory/`

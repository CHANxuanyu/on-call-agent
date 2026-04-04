# Demo Guide

This repo has two main demo scenarios. Both are grounded in the existing replay coverage and both
show the same runtime spine:

`triage -> follow-up -> evidence -> hypothesis -> recommendation -> approval-gated action stub`

Use the replay tests as the live demo entry point so the walkthrough stays aligned with what the
repository actually implements.

## Setup

```bash
python -m pip install -e '.[dev]'
```

## Scenario A: Supported Path

Run:

```bash
pytest tests/integration/test_incident_chain_replay_eval.py::test_incident_chain_replay_eval_runs_supported_hypothesis_chain
```

Fixture:

- `evals/fixtures/incident_chain_recent_deployment.json`

Path to highlight:

- follow-up target: `recent_deployment`
- hypothesis: `deployment_regression`
- recommendation: `validate_recent_deployment`
- action stub: `deployment_validation_candidate`

What it proves:

- the runtime can carry one supported incident theory forward through verifier-backed slices
- stronger evidence can justify a concrete action candidate
- the approval boundary is still explicit, so the harness stops before real execution

## Scenario B: Conservative Path

Run:

```bash
pytest tests/integration/test_incident_chain_replay_eval.py::test_incident_chain_replay_eval_runs_insufficient_evidence_chain
```

Fixture:

- `evals/fixtures/incident_chain_insufficient_evidence.json`

Path to highlight:

- follow-up target: `runbook`
- hypothesis: `insufficient_evidence`
- recommendation: `investigate_more`
- action stub: `no_actionable_stub_yet`

What it proves:

- the runtime stays conservative when the artifact chain does not justify a stronger claim
- verifier-driven transitions can preserve a non-actionable branch cleanly
- approval-aware design exists even when no action candidate should be produced

## Regenerating A Handoff Artifact

After a session exists, regenerate the stable operator-facing handoff artifact with the internal
regenerator:

```python
from context.handoff_regeneration import IncidentHandoffArtifactRegenerator

result = IncidentHandoffArtifactRegenerator().regenerate("session-id")
print(result.status)
print(result.handoff_path)
```

What it writes:

- `sessions/handoffs/<incident_id>.json`

What it uses:

- checkpoint state
- transcript-backed verified artifacts via `SessionArtifactContext`
- `IncidentWorkingMemory` when present

If working memory is absent, regeneration still succeeds when checkpoint plus verified artifacts are
coherent. If the current phase implies a verified artifact should exist and it does not, the
regenerator returns a structured insufficiency or failure result instead of inventing a handoff.

## Artifact Paths To Inspect

During the demo, point at:

- checkpoints: `sessions/checkpoints/<session_id>.json`
- transcripts: `sessions/transcripts/<session_id>.jsonl`
- working memory: `sessions/working_memory/<incident_id>.json`
- handoff artifact: `sessions/handoffs/<incident_id>.json`
- replay runner: `src/evals/incident_chain_replay.py`
- handoff assembly: `src/context/handoff.py`
- handoff writer and regenerator:
  `src/context/handoff_artifact.py` and `src/context/handoff_regeneration.py`

## Engineering Talking Points

- The control plane is checkpoint-driven; the runtime does not resume from handoff artifacts.
- The execution truth is transcript-backed and verifier-gated.
- Synthetic failures keep malformed or partial runtime paths replayable.
- `SessionArtifactContext` removes repeated artifact reconstruction logic without introducing a
  generic planner.
- Incident working memory is a semantic supplement, not a replacement for transcript truth.
- The runtime stops at approval-gated action candidacy on purpose; it demonstrates safety
  boundaries without claiming remediation execution.

# Verifier-Driven Incident Response Agent Harness

Python runtime prototype for incident-response workflows built around verifier-driven state
transitions, append-only transcripts, resumable checkpoints, and approval-aware boundaries. This
repository is not a generic agent demo, not a coding agent, and not an autonomous remediation
system. It is a narrow harness milestone that shows how to make incident-oriented agent behavior
durable, inspectable, replayable, and safe before adding broader automation.

## What This Runtime Is For

The runtime is designed for incident-handling style workflows where correctness of state and
artifacts matters more than demo breadth:

- triaging a structured incident payload
- selecting one deterministic follow-up target
- reading one deterministic evidence bundle
- producing one verifier-backed hypothesis
- producing one verifier-backed recommendation
- surfacing one approval-gated action candidate stub
- generating operator-facing handoff artifacts from durable runtime state

## What It Is Not For

This repository does not implement:

- real remediation or mutation of external systems
- a generic planner or open-ended autonomous loop
- a coding-agent product surface like Claude Code
- multi-agent orchestration
- approval UI or reviewer workflow integration
- external service integrations or production deployment infrastructure

## Why This Is Not A Generic Agent Demo

Most agent demos optimize for broad capability claims or UI. This repository optimizes for harness
engineering:

- verifier-driven completion instead of `"the model returned"`
- append-only JSONL transcripts instead of hidden in-memory state
- checkpoint-driven resumability instead of best-effort retries
- explicit approval boundaries instead of implicit risky autonomy
- replayable fixtures and eval coverage instead of one-off screenshots

The point is to prove a reliable runtime spine, not to claim product completeness.

## Runtime Spine

Current implemented chain:

`triage -> follow-up -> evidence -> hypothesis -> recommendation -> approval-gated action stub`

Each slice is narrow and explicit.

1. `IncidentTriageStep`
   Reads a structured incident payload, emits transcript events, verifies the triage output, and
   writes the first checkpoint.
2. `IncidentFollowUpStep`
   Resumes from checkpoint plus transcript state and either safely no-ops or selects exactly one
   read-only investigation target.
3. `IncidentEvidenceStep`
   Reconstructs the selected target from durable artifacts and reads one deterministic evidence
   bundle.
4. `IncidentHypothesisStep`
   Consumes one verified evidence record and produces exactly one structured hypothesis.
5. `IncidentRecommendationStep`
   Consumes one verified hypothesis and produces exactly one structured advisory recommendation.
6. `IncidentActionStubStep`
   Consumes one verified recommendation and produces exactly one approval-aware action candidate
   stub or one explicit conservative no-actionable outcome.

The chain stops there intentionally. It proves action candidacy and approval state without
executing real write actions.

## Runtime Infrastructure

### Durable Contracts

- file-based skills under `skills/<skill>/SKILL.md`
- typed tools, verifier results, transcript events, and checkpoints
- deterministic local fixtures for replayable evidence

### Execution Truth

- append-only transcript events in `sessions/transcripts/<session_id>.jsonl`
- resumable checkpoints in `sessions/checkpoints/<session_id>.json`
- verifier-driven phase transitions at every implemented slice

### Shared Runtime Layers

- `SessionArtifactContext` loads checkpoint plus transcript once and reconstructs the latest
  verified artifacts
- synthetic failure invariants normalize malformed, missing, or interrupted artifact paths into
  structured replayable failures
- the shared resumable-slice harness centralizes resume, permission, tool, verifier, and
  checkpoint wiring while keeping domain logic inside each step
- permission provenance records why a decision was allowed, blocked, or would require approval

### Semantic Memory And Operator Artifacts

- `IncidentWorkingMemory` stores a compact verified snapshot of current incident understanding
- handoff context assembly builds one read-only operator-facing context object from checkpoint,
  verified artifacts, and working memory
- stable handoff artifacts are written to `sessions/handoffs/<incident_id>.json`
- handoff artifacts can be regenerated deterministically from existing durable state

## Approval Boundary Philosophy

This runtime is deliberately conservative.

- Read-only steps can proceed when policy allows them.
- Stronger evidence can justify a structured action candidate.
- A candidate is still not execution.
- Any future non-read-only action remains outside scope until approval and execution semantics are
  designed explicitly.

That is why the runtime ends at an approval-gated action stub rather than continuing into
remediation.

## Replay / Eval Story

The repo includes replay-style coverage over fixed fixtures, not a generic benchmark harness.

Implemented branches:

- supported branch:
  `recent_deployment -> deployment_regression -> validate_recent_deployment -> deployment_validation_candidate`
- conservative branch:
  `runbook -> insufficient_evidence -> investigate_more -> no_actionable_stub_yet`

These scenarios prove that the harness can carry verified state forward, remain conservative when
evidence is weak, and keep the approval boundary explicit.

## Handoff Artifact Capability

The current milestone includes an operator-facing derived artifact flow:

`SessionArtifactContext -> IncidentHandoffContextAssembler -> IncidentHandoffArtifactWriter`

You can also regenerate the latest handoff artifact from a session id with the internal regenerator:

```python
from context.handoff_regeneration import IncidentHandoffArtifactRegenerator

result = IncidentHandoffArtifactRegenerator().regenerate("session-id")
```

That writes or updates:

- `sessions/handoffs/<incident_id>.json`

The handoff artifact is derived output only. It is not part of the control plane.

## Intentionally Out Of Scope

- real execution or remediation
- human approval UI
- project-memory promotion
- background extraction or compaction systems
- generic planner / workflow engine
- multi-agent orchestration
- API server or end-user product surface

## Validation Commands

Install development dependencies:

```bash
python -m pip install -e '.[dev]'
```

Run the full validation stack:

```bash
ruff check src tests docs
mypy src tests
pytest
```

Run replay coverage only:

```bash
pytest tests/integration/test_incident_chain_replay_eval.py
```

Run the two fixed demo scenarios:

```bash
pytest tests/integration/test_incident_chain_replay_eval.py::test_incident_chain_replay_eval_runs_supported_hypothesis_chain
pytest tests/integration/test_incident_chain_replay_eval.py::test_incident_chain_replay_eval_runs_insufficient_evidence_chain
```

## Repository Structure

```text
src/agent/                     Narrow resumable step runners
src/context/                   Session artifact context, handoff assembly, handoff regeneration
src/runtime/                   Shared harness and synthetic failure normalization
src/tools/implementations/     Deterministic read-only tool actions
src/verifiers/implementations/ Structured verifier logic
src/memory/                    Checkpoints and incident working-memory persistence
src/transcripts/               Typed transcript models and JSONL storage
src/evals/                     Replay/eval runner
skills/                        Durable skill assets
evals/fixtures/                Fixed evidence and scenario fixtures
tests/unit/                    Contract and component tests
tests/integration/             End-to-end slice and replay coverage
docs/                          Architecture, demo, interview, and resume materials
```

## Milestone Status

This repository should be read as a completed runtime milestone, not a finished product.

What is complete for this milestone:

- verifier-gated slice chain from triage through approval-aware action candidacy
- checkpoint plus transcript resumability
- replayable artifact reconstruction through `SessionArtifactContext`
- synthetic failure normalization for malformed or partial runtime paths
- permission provenance and explicit approval-state persistence
- first incident-working-memory slice
- operator-facing handoff assembly, artifact writing, and deterministic regeneration

What is intentionally deferred:

- real execution semantics
- broader memory layering beyond the first incident-working-memory slice
- external approvals, integrations, and product surface

## Additional Docs

- [Architecture Summary](docs/architecture.md)
- [Demo Guide](docs/demo.md)
- [Resume Framing](docs/resume.md)
- [Interview Guide](docs/interview.md)
- [Project Summary](docs/project_summary.md)

# Verifier-Driven Incident Response Agent Harness

Python runtime prototype for a narrow incident-response workflow built around verifier-driven state
transitions, append-only transcripts, resumable checkpoints, and approval-aware boundaries. This
repository is not a generic agent demo, not a coding agent, and not a broad autonomous remediation
system. It is a harness-first milestone that now includes one honest live closed loop for the
`deployment-regression` incident family on a local demo target while keeping the broader system
deliberately narrow, inspectable, replayable, and safe.

## What This Repository Is

This repository implements one explicit incident chain:

`triage -> follow-up -> evidence -> hypothesis -> recommendation -> approval-gated action stub`

For the live `deployment-regression` family, the approved branch continues through:

`bounded rollback execution -> outcome verification`

It is intentionally narrow. The point is to show reliable runtime behavior for incident handling,
not broad planner behavior.

In this repository, "verifier-driven" means a slice is not considered complete just because a tool
or model returned output. Each meaningful slice records transcript events, runs its verifier, and
only then persists the next checkpointed phase. Progression is therefore anchored to verifier
results, not just generated text.

The durable-state seams are explicit:

- checkpoints in `sessions/checkpoints/<session_id>.json`
- append-only transcripts in `sessions/transcripts/<session_id>.jsonl`
- incident working memory in `sessions/working_memory/<incident_id>.json`
- derived handoff artifacts in `sessions/handoffs/<incident_id>.json`

The main operator-facing surfaces are the CLI commands:

- `shell`
- `inspect-session`
- `inspect-artifacts`
- `show-audit`
- `export-handoff`
- `start-incident`
- `resolve-approval`
- `verify-outcome`
- `run-demo-target`
- `list-evals`
- `run-eval`

## What This Runtime Is For

The runtime is designed for incident-handling style workflows where correctness of state and
artifacts matters more than demo breadth:

- triaging a structured incident payload
- selecting one deterministic follow-up target
- reading one deterministic evidence bundle
- producing one verifier-backed hypothesis
- producing one verifier-backed recommendation
- surfacing one approval-gated action candidate stub
- executing one explicit approval-gated rollback against the local demo target
- verifying live post-action runtime state through external endpoint probes
- generating operator-facing handoff artifacts from durable runtime state

## What It Is Not For

This repository does not implement:

- broad remediation or mutation of arbitrary external systems
- a generic planner or open-ended autonomous loop
- a coding-agent product surface like Claude Code
- multi-agent orchestration
- approval UI or reviewer workflow integration
- production deployment infrastructure or third-party ops integrations

## Why This Is Not A Generic Agent Demo

Most agent demos optimize for broad capability claims or UI. This repository optimizes for harness
engineering:

- verifier-driven completion instead of `"the model returned"`
- append-only JSONL transcripts instead of hidden in-memory state
- checkpoint-driven resumability instead of best-effort retries
- explicit approval boundaries instead of implicit risky autonomy
- replayable fixtures and eval coverage instead of one-off screenshots

The point is to prove a reliable runtime spine, not to claim product completeness.

## Quickstart

Install the repository in editable mode:

```bash
python -m pip install -e '.[dev]'
```

List the built-in replay scenarios:

```bash
oncall-agent list-evals
```

Run one supported replay scenario and write its artifacts under a dedicated output root:

```bash
oncall-agent run-eval incident-chain-replay-recent-deployment --output-root /tmp/oncall-agent-demo
```

Expected outcome:

- `path_classification: supported`
- `final_stage: action_stub`
- `handoff_status: written`

The replay run writes a unique subdirectory under the output root, for example:

- `/tmp/oncall-agent-demo/<generated-run-id>/checkpoints/...`
- `/tmp/oncall-agent-demo/<generated-run-id>/transcripts/...`
- `/tmp/oncall-agent-demo/<generated-run-id>/working_memory/...`
- `/tmp/oncall-agent-demo/<generated-run-id>/handoffs/...`

Inspect the resulting session:

```bash
oncall-agent inspect-session incident-chain-replay-recent-deployment-session \
  --checkpoint-root /tmp/oncall-agent-demo/<generated-run-id>/checkpoints \
  --transcript-root /tmp/oncall-agent-demo/<generated-run-id>/transcripts \
  --working-memory-root /tmp/oncall-agent-demo/<generated-run-id>/working_memory
```

Expected outcome:

- `current_phase: action_stub_pending_approval`
- `approval_status: pending`
- transcript and checkpoint paths for the replayed session

Run the live closed-loop deployment-regression demo target in a separate shell:

```bash
oncall-agent run-demo-target --port 8001
```

Use the interactive operator shell as the primary operator surface:

```bash
oncall-agent shell
```

Example shell flow:

```text
/mode semi-auto
/new docs/examples/deployment_regression_payload.json
/approve Rollback approved for the live demo target.
/handoff
/exit
```

`manual`, `semi-auto`, and `auto-safe` are first-class shell modes. `auto-safe` is fail-closed:
the repository-local `.oncall/settings.toml` defaults to `enabled = false`, and auto execution
only occurs for the existing bounded deployment-regression rollback when the policy is enabled and
the exact base URL is allowlisted. Otherwise the shell degrades the session to `semi-auto` and
records the reason durably in checkpoint state.

Start a live incident session from [deployment_regression_payload.json](docs/examples/deployment_regression_payload.json):

```bash
oncall-agent start-incident \
  --family deployment-regression \
  --payload docs/examples/deployment_regression_payload.json \
  --json
```

Approve the bounded rollback candidate and let the runtime execute the rollback plus outcome probe:

```bash
oncall-agent resolve-approval <session_id> --decision approve --json
```

Expected live-path outcome:

- `current_phase: outcome_verification_succeeded`
- `approval_status: approved`
- the action execution and outcome verification stages are verifier-backed and inspectable

For local verification without installing the console script, the same commands also work via:

```bash
.venv/bin/python -m runtime.cli <command> ...
```

If you omit `--output-root` on `run-eval`, the CLI writes replay artifacts under
`sessions/evals/`.

## Runtime Spine

Current implemented chain:

Replay and pre-approval path:

`triage -> follow-up -> evidence -> hypothesis -> recommendation -> approval-gated action stub`

Live approved path for `deployment-regression`:

`triage -> follow-up -> live evidence -> hypothesis -> recommendation -> approval-gated action stub -> bounded rollback execution -> outcome verification`

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
7. `DeploymentRollbackExecutionStep`
   Consumes one approved rollback candidate and executes exactly one bounded rollback against the
   local demo target.
8. `DeploymentOutcomeVerificationStep`
   Probes live deployment, health, and metrics endpoints after rollback and verifies whether the
   target recovered.

The replay path still stops at the approval-gated action stub. The live path continues only for the
single deployment-regression family and only after explicit approval is durably recorded.

## Runtime Infrastructure

### Durable Contracts

- file-based skills under `skills/<skill>/SKILL.md`
- typed tools, verifier results, transcript events, and checkpoints
- deterministic local fixtures for replayable evidence
- one local demo target with live health, deployment, metrics, rollback, and post-action probes

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
- The one implemented non-read-only action is a bounded rollback against the local demo target and
  only runs after approval is explicitly recorded.
- Broader non-read-only actions remain outside scope until they have equally explicit approval and
  verification semantics.

That is why the replay path ends at the action stub while the live path continues only for one
explicitly bounded rollback slice.

## Replay / Eval Story

The repo includes replay-style coverage over fixed fixtures, not a generic benchmark harness.

Implemented branches:

- supported branch:
  `recent_deployment -> deployment_regression -> validate_recent_deployment -> rollback_recent_deployment_candidate`
- conservative branch:
  `runbook -> insufficient_evidence -> investigate_more -> no_actionable_stub_yet`

These scenarios prove that the harness can carry verified state forward, remain conservative when
evidence is weak, and keep the approval boundary explicit.

Built-in operator-facing replay commands:

- `oncall-agent list-evals`
- `oncall-agent run-eval incident-chain-replay-recent-deployment`
- `oncall-agent run-eval incident-chain-replay-insufficient-evidence`

For backward compatibility, `run-eval` also accepts the underscore-style built-in aliases
`incident_chain_recent_deployment` and `incident_chain_insufficient_evidence`, but `list-evals`
shows the canonical hyphenated names.

## Operator CLI Surface

The CLI is intentionally split into two surfaces.

Inspection and export surface:

- `oncall-agent inspect-session <session_id>`
- `oncall-agent inspect-artifacts <session_id>`
- `oncall-agent show-audit <session_id>`
- `oncall-agent export-handoff <session_id>`

Live deployment-regression surface:

- `oncall-agent run-demo-target`
- `oncall-agent start-incident --family deployment-regression --payload <file>`
- `oncall-agent resolve-approval <session_id> --decision approve|deny`
- `oncall-agent verify-outcome <session_id>`

Replay and demo surface:

- `oncall-agent list-evals`
- `oncall-agent run-eval <eval_name>`

The CLI still does not create arbitrary generic agent sessions. It now exposes one explicit live
operator workflow for the deployment-regression family, plus one interactive shell over that same
narrow runtime.

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

- broad unbounded execution or remediation
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

## Repository Map

Key repository entrypoints for reviewers:

- runtime core and harness boundary:
  `src/runtime/harness.py`, `src/runtime/execution.py`
- explicit incident chain:
  `src/agent/incident_triage.py`, `src/agent/incident_follow_up.py`,
  `src/agent/incident_evidence.py`, `src/agent/incident_hypothesis.py`,
  `src/agent/incident_recommendation.py`, `src/agent/incident_action_stub.py`
- durable artifact reconstruction:
  `src/context/session_artifacts.py`
- handoff assembly and regeneration:
  `src/context/handoff.py`, `src/context/handoff_regeneration.py`
- operator CLI surface:
  `src/runtime/cli.py`, `src/runtime/inspect.py`, `src/runtime/eval_surface.py`
- replay/eval entrypoint:
  `src/evals/incident_chain_replay.py`

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

- [Usage Guide](docs/usage.md)
- [Architecture Summary](docs/architecture.md)
- [Demo Guide](docs/demo.md)
- [Resume Framing](docs/resume.md)
- [Interview Guide](docs/interview.md)
- [Project Summary](docs/project_summary.md)

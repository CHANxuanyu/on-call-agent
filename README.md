# Verifier-Driven Incident Response Agent

Python incident-response harness focused on verifier-driven execution, durable artifacts, and
approval-aware state transitions. This repository is not a generic chatbot demo and not an
autonomous remediation system. It is a narrow, production-oriented agent runtime prototype that
proves a disciplined chain from incident triage through recommendation and approval-gated action
stubbing.

## Why This Repo Exists

Most agent demos optimize for breadth, UI, or model behavior. This project optimizes for harness
quality:

- append-only structured transcripts instead of hidden runtime state
- checkpoint-driven resumability instead of best-effort retries
- verifier-driven completion instead of "the model said done"
- explicit approval boundaries before any risky action candidate
- replayable artifact flows that can be tested and inspected end to end

The goal is to show engineering discipline around agent runtimes, not product polish.

## What It Implements

The current milestone is one narrow incident workflow chain:

`triage -> follow-up -> evidence -> hypothesis -> recommendation -> approval-gated action stub`

Each step is deliberately small, typed, and replayable.

### Step Chain

1. `IncidentTriageStep`
   Reads a structured incident payload, emits transcript events, verifies triage output, and
   writes the first checkpoint.
2. `IncidentFollowUpStep`
   Resumes from checkpoint and transcript state, then either safely no-ops or selects exactly one
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

No slice executes a real write action. The chain stops at an approval-gated stub on purpose.

## Core Harness Ideas

### Skills

Skills live as durable assets under `skills/<name>/SKILL.md`. They are file-based, typed through
frontmatter, and intended to remain stable inputs to future runtime behavior.

### Transcripts

Execution history is stored as append-only JSONL with typed events such as:

- `resume_started`
- `model_step`
- `permission_decision`
- `tool_request`
- `tool_result`
- `verifier_result`
- `checkpoint_written`

That transcript is part of the runtime contract, not just debug logging.

### Checkpoints

Session checkpoints capture resumable state such as phase, selected skills, pending verifier, and
approval state. Resume logic reads checkpoints and transcripts together; it does not rely on
ephemeral in-memory state.

### Verifiers

Every implemented slice is verifier-gated. A step is not considered complete because a tool ran or
because a model-shaped function returned. Completion depends on a structured verifier result.

### Replay / Eval

The repo includes a small replay-style eval runner that exercises the chain from fixed fixtures and
asserts structured outcomes and verifier-driven transitions.

### Approval Boundaries

Riskier next steps are surfaced as structured candidates, not executed actions. The current chain
records when approval would be required and persists that boundary into checkpoint state.

## Current Supported Scenarios

The implemented replay coverage focuses on two deterministic scenarios:

- Supported path:
  `recent_deployment -> deployment_regression -> validate_recent_deployment -> deployment_validation_candidate`
- Conservative path:
  `runbook -> insufficient_evidence -> investigate_more -> no_actionable_stub_yet`

These are intentionally small. They exist to prove artifact-driven execution and replay, not to
cover the full space of incident response behavior.

## Deliberately Out Of Scope

The repository does not currently implement:

- real remediation or mutation of external systems
- approval UI or reviewer workflow integration
- a generalized planner or workflow engine
- multi-agent orchestration
- API server or end-user product surface
- broad incident taxonomy or production integrations

## Running The Current Milestone

Install the repo in editable mode with development dependencies:

```bash
python -m pip install -e '.[dev]'
```

Run the full test suite:

```bash
pytest
```

Run the replay coverage only:

```bash
pytest tests/integration/test_incident_chain_replay_eval.py
```

Run the two fixed demo scenarios individually:

```bash
pytest tests/integration/test_incident_chain_replay_eval.py::test_incident_chain_replay_eval_runs_supported_hypothesis_chain
pytest tests/integration/test_incident_chain_replay_eval.py::test_incident_chain_replay_eval_runs_insufficient_evidence_chain
```

Run static checks:

```bash
ruff check .
mypy src tests
```

## Repository Layout

```text
skills/                     Durable skill assets (`SKILL.md`)
sessions/schema/            Checkpoint schema examples
src/agent/                  Narrow resumable step runners
src/tools/implementations/  Deterministic read-only tools
src/verifiers/implementations/ Structured verifier logic
src/transcripts/            Transcript event models and JSONL persistence
src/memory/                 Checkpoint models and storage
src/evals/                  Replay-style eval runner
evals/fixtures/             Fixed scenario and evidence fixtures
tests/integration/          End-to-end slice coverage
tests/unit/                 Contract, tool, and verifier validation
docs/                       Architecture, demo, resume, and interview packaging
```

## Milestone Status

Current milestone: the repository demonstrates a full narrow harness chain from triage through
approval-gated action stubbing, with:

- typed contracts for skills, transcripts, checkpoints, tools, and verifiers
- structured JSONL transcripts and resumable checkpoint state
- verifier-driven phase transitions at every implemented step
- replay coverage for both a supported and a conservative branch
- explicit approval gating before any non-read-only action candidate

This is a harness milestone, not a finished incident-response product.

## Additional Docs

- [Architecture Summary](docs/architecture.md)
- [Demo Guide](docs/demo.md)
- [Resume Bullets](docs/resume.md)
- [Interview Guide](docs/interview.md)

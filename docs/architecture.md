# Architecture Summary

## Purpose

This repository explores a production-oriented incident-response harness built in narrow,
verifier-gated slices. The design is inspired by mature agent harness ideas, but it is adapted to
Python and intentionally stops short of autonomous execution.

The system is built around one question: how do you make an agent runtime resumable, auditable,
and safe enough to reason about before adding more model behavior?

## Durable Contract Layer

The repo starts with explicit contracts instead of an open-ended agent loop.

### Skill Assets

- Skills live under `skills/<skill-name>/SKILL.md`
- Each skill combines machine-readable frontmatter with human-readable guidance
- Skills are durable assets, not prompt fragments hidden in code

### Transcript Events

- Execution history is append-only JSONL
- Each line is a typed event with a stable discriminator
- Current event types include:
  `resume_started`, `model_step`, `permission_decision`, `tool_request`, `tool_result`,
  `verifier_result`, and `checkpoint_written`

### Checkpoints

- Checkpoints persist resumable session state
- They track phase, selected skills, pending verification, approval state, and progress summary
- Resume decisions use checkpoint plus transcript artifacts together

### Verifier Results

- Verifiers return structured `pass`, `fail`, or `unverified`
- State transitions depend on verifier outcomes, not just tool execution

## Why Durable Artifacts Matter

The harness treats transcripts and checkpoints as first-class runtime assets:

- they make execution replayable
- they make resume behavior inspectable
- they make approval boundaries visible
- they make evals deterministic enough to test narrow slices

Without those artifacts, the runtime would depend on hidden control flow and ad hoc state
reconstruction.

## Verifier-Driven State Transitions

The key design rule is simple: returning a result is not enough.

Each implemented step writes artifacts, runs a verifier, and only then advances the session phase.
That keeps the runtime honest about whether it actually reached a justified outcome.

Current narrow chain:

`triage -> follow-up -> evidence -> hypothesis -> recommendation -> approval-gated action stub`

Each slice consumes the structured output of the previous slice and records a new checkpointed
phase.

## Resumability

Resume behavior is artifact-driven, not inference-driven.

Each continuation step:

1. loads the latest checkpoint
2. reads the transcript history
3. reconstructs the prior verified artifact it depends on
4. either proceeds with exactly one narrow action or records an explicit conservative branch

This keeps the chain understandable and debuggable. The step does not guess what happened earlier
from free-form text.

## Approval-Gated Action Candidacy

The current chain stops at an approval-aware action stub rather than executing changes directly.

That step proves two important boundaries:

- stronger evidence can justify producing a structured action candidate
- producing a candidate is still different from executing it

Approval requirements are explicit in structured output and persisted in checkpoint `approval_state`
so that waiting-for-approval is part of the harness state machine, not an implied side effect.

## Replay / Eval Coverage

The repo includes a small replay-style eval over fixed fixtures. It replays the full implemented
chain and checks the structured outputs and verifier-driven transitions for two branches:

- supported branch:
  `recent_deployment -> deployment_regression -> validate_recent_deployment -> deployment_validation_candidate`
- conservative branch:
  `runbook -> insufficient_evidence -> investigate_more -> no_actionable_stub_yet`

This is intentionally not a generalized benchmarking system. It is the beginning of a replayable
artifact flow that can expand later.

## Why Narrow Slices

The implementation deliberately grows one contract-backed slice at a time:

- easier to review
- easier to verify
- easier to replay
- easier to explain in engineering interviews
- less risk of building a vague framework before the artifact model is stable

That tradeoff gives up breadth in exchange for stronger evidence that the harness can support real
stateful agent behavior later.

# Product Principles

These principles govern implementation-facing product work for On-Call Copilot.

## 1. Runtime Truth First

Product surfaces must read from existing runtime truth:

- checkpoints for control state
- append-only transcripts for execution history
- `SessionArtifactContext` for durable artifact reconstruction

Do not introduce a second state model that can drift from the runtime.

## 2. Verifiers Decide Completion

The product must not imply that an incident is resolved because the model or UI says so.

Completion, recovery, and action success must continue to be grounded in verifier-backed artifacts
and externally observed runtime state where available.

## 3. Approval Is A Product Boundary

Approval gating is not an implementation detail. It is part of the product contract.

Product work must keep it obvious:

- when an action is only a candidate
- when approval is still pending
- who approved or denied
- what scope the approval covered

## 4. Safe Incident Decision Loops Over Broad Autonomy

The product should make the current incident loop more usable, not more open-ended.

Prefer:

- better session discovery
- clearer verifier summaries
- better approval ergonomics
- clearer outcome verification

Do not expand into broad autonomous remediation because a UI surface now exists.

## 5. Narrow Scope Is A Feature

The current product is intentionally narrow:

- one live incident family
- one bounded mitigation
- one thin operator-facing shell

Product changes should deepen trust in this scope before expanding it.

## 6. Fail Closed On Missing Or Conflicting State

If the product cannot establish whether automation is safe, it must degrade to a more conservative
operator path and explain why.

Unknown state should become an explicit operator-facing limitation, not hidden behavior.

## 7. Reuse Existing Runtime Seams

Productization should wrap and clarify:

- shell flows
- inspect and audit surfaces
- replay and handoff surfaces
- checkpoint and transcript views

It should not create a second orchestration path that bypasses those seams.

## 8. Make Reasoning Inspectable

Operator-facing product work should make the runtime easier to inspect:

- what phase the session is in
- what evidence mattered
- what verifier ran most recently
- why auto-safe is blocked or degraded
- why an action candidate exists or does not exist

Explainability should come from durable artifacts, not hidden UI state.

## 9. Separate Incident Product From Coding Product

This repository is not a coding copilot. Product work must stay centered on:

- incidents
- mitigations
- approvals
- verifiers
- auditability
- handoff

Do not let the product surface drift toward generic planning, coding, or assistant workflows.

## 10. Product Claims Must Stay Honest

The product may present a cleaner operator experience, but it must not overclaim:

- breadth of incident coverage
- maturity of autonomy
- production readiness
- remediation scope

Every product description should still fit the current repository truth.

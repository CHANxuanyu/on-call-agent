# Metrics

## Product Goal

The product goal for the current repository slice is to reduce time to a safe, decision-ready
incident state without weakening approval boundaries, verifier-backed progression, or durable
auditability.

This is a proto-product metrics frame for a demo-grade system. It is not production telemetry yet.
Where possible, metrics should be derived from existing checkpoints, transcripts, approval
artifacts, verifier outputs, and handoff artifacts rather than a second analytics layer.

## North Star Metric

### Time To Decision-Ready Incident State

Definition:
Elapsed time from session start to the first durable state where the operator can honestly tell
whether the incident is:

- waiting on approval for a bounded action
- conservative and non-actionable
- already verifier-backed as recovered

Why it matters:
This measures the core value of `On-Call Copilot`: compressing the incident decision loop safely.

How it could be observed now:

- session start from the first triage checkpoint or earliest transcript event
- decision-ready state from checkpoint phases such as:
  - `action_stub_pending_approval`
  - `action_stub_not_actionable`
  - `follow_up_complete_no_action`
  - `outcome_verification_succeeded`

Demo-stage approximation:
Measure elapsed time between first durable session record and the first checkpoint that makes the
decision boundary explicit.

## Supporting Metrics

### 1. Decision Velocity

Metric:
Median time from session start to current recommendation or action-candidate visibility.

Why it matters:
The product should reduce time spent reconstructing the incident before a bounded decision is even
possible.

How to observe or approximate:

- use checkpoint timestamps and transcript verifier events
- compare time to hypothesis, recommendation, and action-stub phases

### 2. Approval Flow Efficiency

Metric:
Time from `action_stub_pending_approval` to recorded approval or denial.

Why it matters:
If the product is improving operator clarity, the approval boundary should become easier to review
without becoming easier to bypass.

How to observe or approximate:

- phase timing from checkpoint timestamps
- approval timing from approval-resolution artifacts and transcript events

### 3. Verification Completion Rate

Metric:
Percentage of approved bounded actions that end with an explicit verification outcome rather than
an unverified stopping point.

Why it matters:
The product should drive incidents past execution to externally checked recovery whenever the
runtime path supports it.

How to observe or approximate:

- denominator: sessions with durable approval followed by execution
- numerator: sessions with a verification result surfaced through the existing outcome-verification
  path

### 4. Verification Clarity

Metric:
Percentage of sessions where the latest product surface can clearly show whether recovery is
verified, failed, unavailable, or not yet attempted.

Why it matters:
Operators need to understand the recovery state quickly, not infer it from raw artifacts.

How to observe or approximate:

- inspect whether session detail can populate a verification status and summary from current
  runtime truth

### 5. Handoff Readiness

Metric:
Percentage of sessions that end with either an exported handoff artifact or enough durable state
to assemble one cleanly.

Why it matters:
The product should preserve shift continuity, not just point-in-time execution.

How to observe or approximate:

- existing handoff artifact presence under `sessions/handoffs`
- handoff regeneration success from current session truth

### 6. Explainability Coverage

Metric:
Percentage of session states where the product can answer, from runtime truth, at least these
questions:

- Why is this session blocked?
- Why does an action candidate exist or not exist?
- What does the latest verifier result mean?

Why it matters:
Explainability is a core operator usability feature for this product, especially because approval
and verification are first-class boundaries.

How to observe or approximate:

- current session detail coverage
- recent timeline availability
- assistant support for bounded explanation prompts

## Safety / Trust Metrics

### Unsafe Action Blocked Rate

Definition:
Rate at which the product prevents write execution when approval or safe conditions are missing.

Why it matters:
Unsafe autonomy is a bug for this repository.

How to observe or approximate:

- denied or pending approval sessions that never cross into execution
- `auto-safe` downgrade cases where execution is conservatively blocked

### Approval-Gated Action Rate

Definition:
Percentage of non-read-only actions that go through the explicit approval boundary.

Why it matters:
This metric verifies that risky action semantics have not drifted into silent execution.

How to observe or approximate:

- compare write-action execution events with approval-resolution artifacts

### Verifier-Backed Recovery Confirmation Rate

Definition:
Percentage of executed bounded actions that reach verifier-backed recovery confirmation.

Why it matters:
The product should not stop at action execution if recovery cannot be confirmed.

How to observe or approximate:

- executed rollback sessions that later reach `outcome_verification_succeeded`

### Explainability For Blocked / Ready States

Definition:
Percentage of meaningful session states where the product can surface a concise blocked, ready,
or resolved explanation grounded in durable truth.

Why it matters:
Operators should not need to reverse-engineer state from raw transcript events.

How to observe or approximate:

- session detail completeness
- assistant blocked/ready explanation coverage

### Durable Handoff Availability

Definition:
Percentage of sessions where the operator can retrieve or regenerate a handoff artifact from
durable state.

Why it matters:
Trust includes confidence that operational continuity survives interruption.

How to observe or approximate:

- exported handoff artifact presence
- regeneration success over current checkpoints, transcripts, and artifacts

## Adoption / Usage Signals

These are product-like signals, but they should still be interpreted as demo-stage usage rather
than mature telemetry.

### Session Detail Engagement

Signal:
Percentage of sessions where the operator views session detail after opening the sessions list.

Why it matters:
Shows whether the product is actually helping users move from discovery to understanding.

How to observe or approximate:

- console route hits in a demo environment
- shell flow sequences such as `/sessions` followed by `/resume` and `/status`

### Assistant Use After Context Review

Signal:
Percentage of sessions where the assistant is used after the operator has already opened incident
detail or timeline.

Why it matters:
Reinforces that the assistant is secondary to the panel-first workflow, not the primary product.

How to observe or approximate:

- console API sequence: detail or timeline request before assistant request

### Verify After Action Rate

Signal:
Percentage of sessions with executed bounded action where the operator runs or inspects
verification.

Why it matters:
Shows whether the product is reinforcing recovery validation, not just action execution.

How to observe or approximate:

- verification route access after approval/execution
- shell `/verify` usage after approval

### Handoff Export Rate

Signal:
Percentage of sessions ending with handoff export.

Why it matters:
Reflects whether the product is supporting shift continuity rather than only point-in-time action.

How to observe or approximate:

- handoff export actions
- handoff artifact file creation

### Repeated Explainability Prompt Use

Signal:
Reuse of prompts such as:

- blocked-state explanation
- evidence explanation
- approve-vs-deny comparison
- verifier explanation

Why it matters:
These indicate whether the assistant is helping operators interpret runtime truth in practice.

How to observe or approximate:

- assistant request intent classification from the existing session-scoped assistant surface

## Demo-Stage Proxy Metrics

Because the current repo is demo-grade, the first useful metrics are likely proxies rather than
production-grade analytics.

Good early proxies:

- time from session start to `action_stub_pending_approval`
- time from approval to verification result
- percentage of sessions ending with exported handoff
- percentage of bounded actions followed by verify
- percentage of assistant prompts that match supported explainability intents
- percentage of auto-safe attempts that correctly degrade when safe conditions are not met

These proxies are credible because they can be approximated from current runtime truth and product
surfaces without inventing a second telemetry model.

## What Should Not Be Optimized Yet

Do not optimize prematurely for:

- raw number of automated actions taken
- chat message volume
- time to execution without considering approval and verification
- breadth of incident-family coverage before the current narrow loop is solid
- vanity UI engagement metrics disconnected from operator outcomes
- claims of production SLA improvement without real deployment evidence

The product should optimize for safe decision compression, not for looking broadly autonomous.

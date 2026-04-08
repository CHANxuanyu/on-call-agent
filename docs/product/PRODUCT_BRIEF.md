# Product Brief

## Product Identity

`On-Call Copilot` is the operator-facing product direction for this repository.

It is a thin product layer over the existing verifier-driven, durable, approval-gated
incident-response runtime. Today it is grounded in one honest live path for the
`deployment-regression` incident family, with external outcome verification and a narrow
operator shell.

This document is the controlling product spec for future product-facing work in this repository.
If a proposed feature conflicts with this brief, the brief wins unless it is explicitly updated.

## Precedence and Controlling Specs

Use the repository documents in this order when there is tension between product ideas and
existing system behavior:

1. Runtime truth and architecture constraints come first.
   This means the implemented runtime behavior, durable artifacts, and
   [Architecture Summary](../architecture.md) override product wishfulness.
2. This product brief controls product direction, boundaries, and positioning.
3. Phase PRDs must refine this brief, not override it.
4. `README.md` is the landing-page summary, not the authority for expanding scope.

If a proposed UI or workflow improvement conflicts with runtime truth in checkpoints, transcripts,
`SessionArtifactContext`, verifier contracts, or approval boundaries, the runtime constraints win.

## What The Product Is

On-Call Copilot is an incident decision and verification product for operators.

Its job is to help an operator:

- open or resume an incident session
- inspect durable incident state and recent activity
- understand the current hypothesis, evidence, and verifier status
- review or deny approval-gated mitigation candidates
- verify whether the bounded mitigation actually worked
- export handoff-ready artifacts from durable runtime truth

It is not a generic coding agent and not a generic autonomous remediation platform.

## Who It Is For

Primary users:

- on-call engineers
- incident commanders for narrow operational incidents
- operators reviewing whether a bounded mitigation is safe to run

Secondary users:

- engineering reviewers evaluating agent harness quality
- interviewers assessing reliability, resumability, safety, and verification design

## Core Value

The product value is incident decision compression, not broad agent capability.

On-Call Copilot should make it easier to:

- compress a noisy incident into a clear operator decision:
  whether to act now, which bounded action is safe, and how recovery is verified
- keep incident state durable and reconstructable
- see why the runtime believes a mitigation is or is not warranted
- preserve explicit approval boundaries for risky actions
- verify recovery against external runtime state instead of model narrative
- resume, audit, replay, and hand off work without relying on raw chat history

## Why This Is Not Claude Code

Use this wording consistently:

Claude Code is a coding copilot.
On-Call Copilot is an incident decision and verification product.
Claude Code helps engineers change systems.
On-Call Copilot helps operators decide whether to act now, which bounded action is safe, and how
recovery is verified.

## Why It Exists Separately From Claude Code

Claude Code is a coding copilot. Its center of gravity is code understanding, editing, and
developer workflow acceleration.

On-Call Copilot is an incident decision and verification product. Its center of gravity is:

- incident state, not source code editing
- durable runtime truth, not conversational context alone
- verifier-backed progression, not open-ended agent exploration
- approval-gated mitigation, not broad tool execution
- bounded operational actions, not generic coding tasks

This repository can borrow harness ideas from coding-agent systems, but it must not drift into
"Claude Code for ops" positioning.

## Boundaries That Must Remain Intact

The following product boundaries are mandatory:

- verifier-backed progression remains the primary completion contract
- verifier execution remains explicitly staged as contract validation, then outcome validation
- risky or write actions remain approval-gated unless a narrowly defined safe policy explicitly
  allows otherwise
- the latest committed control truth is the reconciled checkpoint plus its matching
  `checkpoint_written` transcript boundary, not a checkpoint file in isolation
- transcript-backed execution history remains explicit, including uncommitted tail state and
  transcript-backed verifier interruption
- bounded `IncidentPhase` validation remains in true phase-bearing contract fields; invalid phase
  fails closed and valid-but-incompatible phase is handled explicitly
- wrong-step runtime entry must fail closed before new durable writes
- product surfaces must reuse existing runtime artifacts as thin readers/controllers instead of
  inventing a second state layer
- any autonomy must fail closed when evidence, policy, or runtime state is missing or inconsistent
- the current live product scope remains narrow and incident-family specific
- operator behavior must stay explicit, inspectable, and auditable

## Explicitly Out Of Scope

The following are out of scope unless the product brief is intentionally revised:

- a generic coding agent
- a generic planner or chatbot
- broad autonomous remediation across arbitrary systems
- silent policy bypass or hidden auto-approval
- a second orchestration runtime separate from the current harness
- hidden mutable UI state that cannot be reconstructed from durable artifacts
- multi-agent complexity without a clear product need
- product claims that imply mature production readiness

## Existing Runtime Assets That Must Be Preserved

Product work must preserve these existing repository assets:

- the explicit incident chain and verifier sequence
- explicit verifier contract-stage then outcome-stage flow
- append-only JSONL transcript history
- resumable checkpoints as committed control state
- `SessionArtifactContext` as the durable recovery and audit seam
- committed-prefix-only trusted artifact reconstruction from reconciled checkpoint plus transcript
- transcript-backed `verifier_request` interruption representation and committed-only
  `pending_verifier` control state
- approval provenance and approval-resolution artifacts
- `IncidentWorkingMemory` and derived handoff artifacts
- replay and eval surfaces
- the current operator console and operator shell as thin surfaces over the same runtime truth
- the current bounded deployment-regression rollback path and outcome verifier

## Current Productization Phase

The repository is in an early productization phase: a demo-grade incident-response product with one
real incident family, one bounded mitigation, and thin console plus shell surfaces over the same
runtime truth.

The next product work should improve operator usability and incident clarity without changing the
runtime into a broader autonomous system. Productization should make the existing runtime easier to
operate, inspect, and explain before it expands in scope.

## What Success Looks Like

Success for the current product direction means:

- a reviewer can understand the product in operator terms, not only runtime-internals terms
- an operator can work through the existing incident loop from one product surface
- approvals, verifier outcomes, evidence, and recovery state stay explicit and durable
- the product remains honest about its narrow scope and demo-grade status
- future slices deepen credibility, auditability, and operator usability instead of adding vague
  breadth

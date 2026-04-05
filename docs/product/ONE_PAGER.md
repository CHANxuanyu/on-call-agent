# On-Call Copilot

_A narrow product prototype over a verifier-driven incident-response runtime._

## Problem

During a live operational incident, the hard part is often not gathering more raw output. The hard
part is compressing the decision loop safely:

- is the incident actually actionable now
- is the bounded mitigation justified
- who needs to approve it
- did recovery really happen
- can the next operator resume cleanly

Many incident workflows still split those questions across commands, partial notes, and human
memory. That makes approval slower, recovery claims easier to overstate, and handoff continuity
fragile.

`On-Call Copilot` exists to make that decision window clearer for one bounded operational path.

## Who It Is For

Primary user:

- on-call engineer or operator handling a bounded live `deployment-regression` incident

Secondary users:

- incident commander or senior approver reviewing a bounded rollback candidate
- next-shift operator resuming the session after approval, denial, or verification activity

## Why This Exists Separately From A Generic Coding Agent

Claude Code is a coding copilot.
On-Call Copilot is an incident decision and verification product.
Claude Code helps engineers change systems.
On-Call Copilot helps operators decide whether to act now, which bounded action is safe, and how
recovery is verified.

The center of gravity is different:

- incident state, not source editing
- durable runtime truth, not conversational context alone
- approval-gated bounded action, not broad tool execution
- verifier-backed recovery, not “the model says it worked”
- handoff continuity, not coding workflow acceleration

## Product Surface

The product is panel-first, not chat-first.

Current surfaces:

- sessions view
- incident detail view
- recent timeline of checkpoint, verifier, approval, execution, and verification activity
- approval / deny controls for the bounded rollback candidate
- verification result display
- handoff export access

The assistant is session-scoped and secondary. It explains the selected session, summarizes recent
activity, clarifies blocked vs ready state, and drafts operator-facing summaries. It does not own
incident state, approval state, or recovery state.

## Core Value

The core value is safe incident decision compression.

In the current repository slice, that means:

- reduce time to a decision-ready incident state
- keep risky action bounded and approval-gated
- make recovery verification explicit and externally grounded
- preserve durable continuity across interruption and shift handoff

## Safety Model

The product inherits its safety model from the runtime rather than inventing a separate one.

Key boundaries:

- approval gating for risky or write action
- verifier-backed recovery instead of model-declared success
- append-only transcripts for execution history
- checkpoints for current control state
- `SessionArtifactContext` for durable artifact reconstruction
- assistant responses grounded in session truth but kept non-authoritative

## Current Honest Scope

This is the current product slice, not a mature ops platform.

Today the repo supports:

- one incident family: `deployment-regression`
- one bounded mitigation path: rollback to the known-good version
- one local demo target
- one operator shell and one thin panel-first console layer over the same runtime

It does not currently claim:

- broad multi-incident coverage
- broad autonomous remediation
- production integrations
- mature production readiness

## What Success Looks Like

For the current slice, success looks like:

- an operator can move from page to decision-ready state quickly
- the approval boundary is clear and durable
- recovery is confirmed from external runtime evidence when the bounded action runs
- the next operator can resume from session truth instead of rebuilding context manually
- a reviewer can see this as a credible AI product direction, not just a collection of harness
  internals

## Near-Term Roadmap

The near-term roadmap remains intentionally narrow:

1. Phase 1: stronger operator console over existing runtime truth
2. Phase 2: a second incident family without collapsing into generic orchestration
3. Phase 3: clearer metrics, policy visibility, and more polished product surfaces over the same
   durable runtime

The goal is to deepen trust and operator usability before expanding breadth.

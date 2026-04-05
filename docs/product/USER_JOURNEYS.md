# User Journeys

## Framing

`On-Call Copilot` is opened during a live operational decision window, not during a general
exploration session.

The product is panel-first:

- sessions
- incident detail
- timeline
- approval / deny
- verification
- handoff access

The assistant pane is secondary and session-scoped. It explains the selected session, but it does
not become workflow authority.

## Journey 1: Page To Decision-Ready Understanding

### User

On-call engineer / operator

### Trigger

A service page or alert suggests a recent deployment regression and the operator needs to
understand whether action is warranted.

### User goal

Turn the current session into a decision-ready view quickly enough to know whether the runtime is
waiting on approval, already resolved, or still conservative and non-actionable.

### Preconditions

- a session exists or can be started from the current incident payload
- the current runtime has enough durable artifacts to reconstruct session detail
- the incident is within the current `deployment-regression` product boundary

### Main flow

1. The operator opens the shell or console and finds the relevant session.
2. The product surfaces session identity, phase, approval state, mode, evidence summary, and the
   latest verifier summary.
3. The operator reviews the recent timeline to understand what happened most recently.
4. If needed, the operator uses the session-scoped assistant to ask bounded questions such as
   “Why is this session blocked?” or “What evidence supports the current recommendation?”
5. The operator reaches a decision-ready understanding of whether the session is actionable,
   pending approval, already verified, or conservatively blocked.

### Product surfaces involved

- sessions view
- session detail view
- recent timeline
- session-scoped assistant pane

### Edge cases / bounded failure modes

- the session may already be healthy and therefore non-actionable
- the current phase may show that approval was denied earlier
- verifier-backed evidence may be incomplete, forcing a conservative state
- artifacts may be missing or malformed, in which case the runtime should fail closed rather than
  fabricate clarity

### Product value delivered

- compresses the time from page to decision-ready incident understanding
- reduces the need to inspect raw transcript JSON immediately
- keeps the explanation grounded in durable session truth

### Current limitations of the repo

- only one live incident family is supported
- evidence gathering is scoped to the local demo deployment-regression path
- the assistant is intentionally narrow and deterministic, not a broad reasoning copilot

### Future opportunities

Future work could improve multi-session comparison, richer evidence visualization, or broader
session filtering, but only if those views remain projections of existing runtime truth.

### End state

The operator can clearly say: “This session is waiting on approval,” “This session is already
verified,” or “This session is conservative and currently has no safe action candidate.”

## Journey 2: Approval-Gated Action To Recovery Verification

### User

On-call engineer together with the senior approver / incident commander

### Trigger

The runtime has reached a bounded rollback candidate and is waiting at the approval boundary.

### User goal

Review the candidate, approve or deny intentionally, and then determine whether recovery is
externally verified.

### Preconditions

- the current session is at or near `action_stub_pending_approval`
- the bounded rollback candidate exists through the current verified artifact chain
- the operator is within the current deployment-regression live path

### Main flow

1. The operator reviews the current recommendation, safety notes, and approval status.
2. The approver uses the product surface to approve or deny the bounded rollback candidate.
3. If approved, the existing runtime records approval durably and runs the bounded rollback path.
4. The product surfaces execution completion and the latest verification result.
5. The operator verifies whether recovery is confirmed from external runtime state.

### Where approval matters

Approval is the product boundary between a candidate and write execution. The console or shell can
surface the decision, but it must reuse the existing approval-resolution seam and durable approval
records.

### Where verification matters

Verification determines whether the mitigation actually worked. The product must not imply success
until the outcome verifier and external runtime evidence support recovery.

### Edge cases / bounded failure modes

- the approver may deny the action candidate
- `auto-safe` may degrade to `semi-auto` because safe conditions are not met
- rollback execution may complete but verification may fail or remain unavailable
- the service may already be healthy, in which case the runtime should not propose a rollback
  candidate in the first place

### Product value delivered

- makes the approval boundary explicit instead of implicit
- keeps action scope bounded and inspectable
- ties recovery claims to verifier-backed runtime evidence

### Current limitations of the repo

- only one bounded write action exists today: rollback to the known-good version
- the live path is local-demo-target oriented
- the product does not yet support broad policy authoring, multi-team approval routing, or rich
  rollback strategy selection

### Future opportunities

Future work could improve policy explainability and approval ergonomics, but it should not weaken
the current approval boundary or broaden action scope casually.

### End state

The session lands in one of the honest bounded outcomes:

- denied and non-executing
- executed and waiting on verification
- verifier-backed recovery confirmed

### What remains intentionally manual or bounded

- the operator still owns the approval decision
- only the current bounded rollback path may execute
- recovery still depends on explicit verification rather than assistant narrative

## Journey 3: Operator Handoff / Shift Continuity

### User

Next-shift operator

### Trigger

The incident is being handed over, resumed after interruption, or reviewed after a decision was
already made.

### User goal

Resume from durable session truth without relying on fragile chat context or ad hoc notes.

### Preconditions

- the session has checkpoint and transcript history
- the current artifact chain can be reconstructed through `SessionArtifactContext`
- if available, handoff export has been written from the existing regeneration seam

### Main flow

1. The next operator opens the session from the sessions list or resume surface.
2. The product shows current phase, approval status, latest verifier result, and recent timeline.
3. The operator reviews the exported handoff artifact if it exists.
4. If needed, the operator asks the assistant for a plain-English explanation of the latest state
   or a summary of recent activity.
5. The next operator resumes work from durable session truth instead of rebuilding the incident
   narrative manually.

### Role of durable session state, transcript, and handoff export

- checkpoints provide the current control state
- transcripts preserve what happened in order
- `SessionArtifactContext` reconstructs the usable artifact chain
- handoff export provides operator-readable continuity, but it remains derived from the durable
  runtime layers above

### Edge cases / bounded failure modes

- the handoff artifact may not exist yet
- working memory may be absent or stale compared with newer verified artifacts
- the current session may reflect denial or resolved recovery rather than an active incident

### Product value delivered

- preserves continuity across shift changes and interruptions
- reduces the need to reread raw execution history line by line
- keeps handoff grounded in the same durable runtime truth used for resume and audit

### Current limitations of the repo

- handoff content is only as broad as the current narrow incident family and artifact chain
- there is no broader case-management layer beyond the current session-centric runtime
- the assistant does not maintain a durable multi-turn operational conversation

### Future opportunities

Future work could improve handoff views, timeline compaction, or multi-operator annotations, but
only if they stay clearly separated from workflow authority.

### End state

The next operator can state what phase the incident is in, what decision already happened, what
the verifier says now, and whether any further bounded action is still possible.

## Why This Is Not Chat-First

The product is centered on incident state, timeline, approval, verification, and handoff. The
assistant pane is useful because it explains those surfaces; it does not replace them.

If the chat pane disappeared, the product would still have its core workflow. If durable session
truth disappeared, the product would lose its core value.

## Why This Is Not A Coding Workflow

Claude Code helps engineers change systems. On-Call Copilot helps operators decide whether to act
now, which bounded action is safe, and how recovery is verified.

The central artifacts here are checkpoints, transcripts, verifier outputs, approval records, and
handoff artifacts, not source edits or implementation plans.

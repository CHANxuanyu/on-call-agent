# Personas

## Scope Note

This persona set is for the current narrow operator-facing product slice only.

`On-Call Copilot` is currently a session-centric incident decision and verification product for
one live incident family: `deployment-regression`. These personas are grounded in the product as
it exists today: panel-first console and shell surfaces over durable runtime truth, one
approval-gated rollback path, external outcome verification, and handoff continuity.

## Primary Persona: On-Call Engineer / Operator

### Role

The engineer actively handling a bounded live incident for a service they support.

### When they open the product

- when an alert or page points to a recent deployment regression
- when they need to turn noisy operational evidence into a safe decision quickly
- when they need to know whether the runtime is ready for approval, blocked, or already verified

### Core pain points

- incident state is fragmented across commands, logs, and partial notes
- it takes time to determine whether a rollback is actually justified
- approval boundaries can be unclear in ad hoc workflows
- recovery claims are easy to overstate before external verification completes

### What they need from the product in that moment

- one session workspace that shows current phase, evidence, recommendation, approval state, and
  verifier status
- a clear answer to whether the runtime is blocked, ready for approval, or already verified
- a bounded action candidate, not a vague remediation brainstorm
- confidence that recovery is grounded in external runtime checks, not just model narrative

### What success looks like for them

- they reach a decision-ready incident state quickly
- they can approve or deny the bounded rollback with clear context
- they can verify whether recovery actually happened
- they can hand off the incident without rebuilding context from scratch

### What they do not need from the product

- a generic chatbot
- a broad autonomous remediation engine
- coding help, refactoring advice, or source-editing workflows
- a second incident state model that disagrees with checkpoints or transcripts

### Why they would use this instead of a generic coding agent

A coding copilot helps change systems. This product helps decide whether to act now, which
bounded action is safe, and how recovery is verified from runtime truth. In this operational
moment, durable incident state, approval gating, and verification matter more than code generation.

## Secondary Persona: Incident Commander / Senior Approver

### Role

The person responsible for reviewing and approving or denying the bounded mitigation candidate.

### When they open the product

- when the session reaches the approval boundary
- when they need to understand why a rollback candidate exists
- when they need to confirm whether the requested action stayed within approved scope

### Core pain points

- approval requests often arrive without enough evidence context
- it is hard to see whether a mitigation is still pending, already executed, or already verified
- audit history can be too raw to scan quickly during a live decision window

### What they need from the product in that moment

- a compact explanation of the current evidence and recommendation
- clear approval status and the exact bounded action being reviewed
- the latest verifier result and recovery status after any approved action
- an inspectable recent timeline of approval, execution, and verification activity

### What success looks like for them

- they can approve or deny with clear bounded scope
- the approval decision is durable and inspectable afterward
- they can confirm whether the runtime stayed inside the intended approval boundary

### What they do not need from the product

- broad operational automation across arbitrary systems
- hidden auto-approval behavior
- a chat thread that becomes the real source of decision state

### Why they would use this instead of a generic coding agent

The job here is not writing code. It is reviewing an evidence-backed operational decision with a
durable audit trail and external verification path.

## Secondary Persona: Next-Shift Operator

### Role

The operator who inherits the incident after approval, denial, or verification activity has
already happened.

### When they open the product

- during shift handoff
- when resuming a session after interruption
- when they need to understand what already happened without replaying raw logs manually

### Core pain points

- context is often trapped in chat history or human memory
- it is difficult to tell which steps were verifier-backed and which were just proposals
- handoff notes are often incomplete or disconnected from actual runtime state

### What they need from the product in that moment

- durable session identity and current phase
- a concise explanation of recent timeline activity
- access to verifier-backed evidence, approval state, and any exported handoff artifact
- confidence that they are resuming from actual session truth, not stale operator notes

### What success looks like for them

- they can resume the session quickly
- they can tell whether the incident is still active, denied, or already verified as recovered
- they can continue from durable artifacts instead of reconstructing state manually

### What they do not need from the product

- an open-ended planning assistant
- a new workflow that diverges from the original durable session record
- a handoff story that is disconnected from checkpoints, transcripts, or verifier outputs

### Why they would use this instead of a generic coding agent

The resume problem here is operational continuity, not code editing. The value comes from durable
session truth, auditability, and recovery verification.

## Who This Product Is Not For Yet

This product is not for:

- teams looking for a broad incident-management platform across many incident families
- operators expecting autonomous remediation across arbitrary systems
- engineers primarily seeking a coding copilot
- organizations expecting mature production telemetry, policy management, or enterprise workflow
  integrations today

The current slice is intentionally narrow: one live incident family, one bounded mitigation, and
one operator-facing decision loop.

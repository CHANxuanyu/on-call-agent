# Phase 1 Operator Console PRD

## Purpose

Phase 1 defines the first product console slice for On-Call Copilot.

The goal is to give an operator a stronger session-centric workspace over the existing runtime,
without creating a second runtime or weakening existing approval and verifier boundaries.
It is not a chat-first generic agent UI. It is an operator console over durable runtime truth.

## Product Goal

An operator should be able to manage the current incident lifecycle from one console surface:

- find and resume sessions
- inspect the current incident state
- review recent transcript, verifier, and checkpoint activity
- approve or deny the one bounded mitigation candidate
- inspect verification results
- access handoff export

## Target User

The target user is an operator handling a narrow on-call incident who needs a clearer, more
product-like workspace than raw commands alone.

## Scope

Phase 1 covers six product capabilities only.

### 1. Sessions View

The product should show recent sessions from durable state, including where available:

- session id
- incident id
- incident family
- current phase
- requested mode
- effective mode
- approval state
- latest verifier summary
- last updated time

Data must come from existing checkpoint and transcript artifacts.

### 2. Incident Detail View

The product should show a compact operator-facing incident summary with:

- session and incident identity
- family
- current phase
- current step if known
- requested and effective mode
- downgrade reason if present
- approval status
- next recommended action
- current evidence summary
- latest verifier summary
- handoff availability

This view should summarize durable truth, not dump raw artifacts by default.

### 3. Transcript / Verifier / Checkpoint Timeline

The product should show a compact recent timeline built from existing transcript and checkpoint
artifacts, including:

- recent phase transitions
- verifier outcomes
- approval events
- execution events
- outcome verification events

This is a product view over the existing audit trail, not a second audit system.

### 4. Approval / Deny Actions

The product should allow the operator to:

- approve the current bounded rollback candidate
- deny that candidate with an explicit reason

These actions must reuse the existing approval-resolution path and preserve durable approval
records.

### 5. Verification Result Display

The product should show the last known outcome verification result clearly, including:

- whether verification passed or failed
- the externally observed runtime state that mattered
- whether recovery is considered verified or still unresolved

### 6. Handoff Export Access

The product should expose whether a handoff is available and allow the operator to export or view
it through the existing handoff surface.

## Required Product Constraints

Phase 1 must preserve these constraints:

- no second state store
- no bypass of verifier-backed progression
- no bypass of approval boundaries
- no broadening beyond the current deployment-regression family
- no generic action library
- no broad autonomy claims

## Non-Goals

Phase 1 does not include:

- a general-purpose incident management product
- support for multiple live incident families
- hidden background automation outside the existing runtime
- broad autonomous remediation
- a full-screen TUI or web application requirement
- changes to checkpoint, transcript, or handoff schemas unless strictly necessary later

## Explicit Non-Goals

Phase 1 must not be implemented as:

- a chat-first generic agent interface
- a general-purpose assistant or planner
- a second orchestration layer that invents its own session state
- an approval-bypassing action launcher
- a UI that claims incident resolution without verifier-backed evidence
- a broad remediation console for arbitrary systems or actions

## Acceptance Criteria

Phase 1 is successful when:

- an operator can find the right recent session from durable state and resume it without guessing
  which direct CLI command to run next
- an operator can determine from one console view whether the current incident needs action now,
  is waiting on approval, has been denied, or has verified recovery
- an operator can understand why the current bounded rollback candidate exists, or why no action is
  available, without reading raw transcript JSON by default
- an operator can review the recent timeline of verifier, approval, execution, and checkpoint
  events quickly enough to reconstruct what happened in the session
- an operator can approve or deny the current bounded mitigation through the existing durable
  approval path and see the resulting state transition clearly
- an operator can inspect the latest verification result and tell whether recovery is externally
  verified or still unresolved
- an operator can access handoff export from the same console surface when the session is ready
- the console remains a thin operator product layer over the runtime rather than a generic agent UI

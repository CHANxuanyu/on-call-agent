# Phase 1.5 Assistant Pane Mapping

This document explains how the Phase 1.5 session-scoped assistant pane maps to existing runtime
truth.

The assistant is not workflow authority. It is a bounded explanation surface over one selected
session.

## Canonical vs Non-Canonical

### Workflow authority / canonical runtime truth

These remain authoritative for incident control state, approval state, and verifier-backed
progression:

- session checkpoint JSON
- append-only transcript events
- approval state recorded through the existing runtime
- verifier-backed artifacts reconstructed through `SessionArtifactContext`

`SessionArtifactContext` is the canonical reconstruction seam over checkpoint and transcript
truth. It does not create a second authority layer.

### Supporting derived context

These can help explain the session, but they do not control workflow state:

- `IncidentWorkingMemory`
- existing handoff artifacts

### Non-canonical interaction state

These are not authoritative:

- the operator prompt text sent to the assistant
- any browser-visible prior prompts and answers shown in the assistant pane

In this slice, browser-side message history is ephemeral only. It is not written to checkpoints,
transcripts, working memory, or handoff artifacts. The backend answers each request from the
current `session_id` plus the current prompt only.

## Backend Surfaces

| Surface | Route | Backend adapter | Workflow-authoritative sources | Supporting context |
| --- | --- | --- | --- |
| Sessions list | `GET /api/phase1/sessions` | `OperatorConsoleAPI.list_sessions()` | checkpoints + transcripts | none |
| Session detail | `GET /api/phase1/sessions/{session_id}` | `OperatorConsoleAPI.get_session_detail()` | checkpoint + transcript + `SessionArtifactContext` | existing handoff artifact when available |
| Timeline | `GET /api/phase1/sessions/{session_id}/timeline` | `OperatorConsoleAPI.get_session_timeline()` | transcripts only | none |
| Approval / deny | `POST /api/phase1/sessions/{session_id}/approval` | `OperatorConsoleAPI.resolve_approval()` | existing approval-resolution live surface | none |
| Verification rerun | `POST /api/phase1/sessions/{session_id}/verification` | `OperatorConsoleAPI.rerun_verification()` | existing outcome-verification live surface | none |
| Handoff export | `POST /api/phase1/sessions/{session_id}/handoff/export` | `OperatorConsoleAPI.export_handoff_artifact()` | existing handoff regeneration seam | existing working memory or prior handoff may inform the export |
| Assistant prompt | `POST /api/phase1/sessions/{session_id}/assistant` | `SessionAssistantAPI.respond()` | checkpoint + transcript + `SessionArtifactContext` | working memory and handoff artifact when available |

## Assistant Intent Grounding

### 1. Current state explanation

Uses:

- checkpoint `current_phase`, `approval_state`, `operator_shell`
- current session detail projection from `OperatorConsoleAPI`
- latest verifier summary from transcript events

### 2. Recent timeline summary

Uses:

- `OperatorConsoleAPI.get_session_timeline()`
- transcript `checkpoint_written`, `verifier_result`, `approval_resolved`,
  `permission_decision`, `resume_started`, rollback tool, and outcome-probe tool events

### 3. Blocked or ready explanation

Uses:

- checkpoint phase
- approval status
- requested/effective mode and downgrade reason
- verification availability from `OperatorConsoleAPI.get_verification_result()`

The assistant does not invent new blocked states. It explains the current runtime state only.

### 4. Approve vs deny consequences

Uses:

- current phase and approval status from checkpoint
- verified action-stub artifact chain through `SessionArtifactContext`
- existing live-surface semantics for the bounded rollback path

The assistant explains what the existing approval surface will do. It does not execute actions.

### 5. Evidence summary

Uses:

- verified evidence artifact from `SessionArtifactContext`
- verified hypothesis and recommendation artifacts when present
- working memory only as supporting compact semantic context

### 6. Verifier explanation

Uses:

- latest transcript verifier summary
- current outcome-verification artifact availability from `SessionArtifactContext`
- post-action probe output when verifier-passed

### 7. Handoff-ready summary draft

Uses:

- existing handoff artifact if one already exists
- otherwise `IncidentHandoffContextAssembler` over checkpoint, transcripts, working memory, and
  verifier-backed artifacts

Important:

- the handoff draft is derived from canonical runtime truth
- working memory and any existing handoff artifact are supporting derived context only
- exporting handoff writes a durable operator artifact, but that artifact still does not become
  workflow authority
- the assistant route does not write handoff artifacts

## Why Chat Stays Secondary

The main Operator Console remains panel-first:

- sessions
- incident detail
- timeline
- approval / deny actions
- verification
- handoff access

The assistant pane is attached to one selected session and only translates existing runtime truth
into operator-facing language. It does not become a chat-first landing page and it does not carry
its own incident status model.

## Invariants

- no second workflow state layer
- no chat-owned incident state
- no chat-owned approval state
- no chat-owned recovery state
- no approval bypass
- no verifier bypass
- no broadened incident-family scope
- shell, CLI, and `OperatorConsoleAPI` remain valid operator surfaces over the same truth

# Phase 1.5 Assistant Pane Plan

## Goal

Add a narrow, session-scoped assistant pane to the Phase 1 Operator Console without changing the
runtime control model.

The assistant is a secondary operator aid. It explains and summarizes one existing incident
session. It does not become workflow authority.

## Architectural Constraints

- runtime truth remains canonical:
  checkpoints, append-only transcripts, `SessionArtifactContext`, approval artifacts, verifier
  outputs, verification artifacts, working memory, and handoff artifacts remain the source of
  truth
- no second workflow state layer
- no chat-owned incident status, approval state, recovery state, or action state
- no new planner loop and no generic remediation behavior
- no approval bypass and no verifier bypass
- preserve existing shell, CLI, and `OperatorConsoleAPI` behavior
- stay inside the current deployment-regression product boundary

## Scope

Implement one thin Phase 1.5 slice:

1. a session-scoped assistant adapter over existing console/runtime truth
2. a minimal console server with narrow JSON routes
3. a small panel-first HTML view with the assistant as a secondary session-detail pane
4. focused tests and mapping docs

## Explicit Non-Goals

- no generic chat-first agent product
- no LLM-backed open-ended reasoning loop
- no hidden conversational workflow state
- no persistent assistant state that can drift from checkpoints or transcripts
- no replacement of the shell as the main existing operator surface
- no expansion beyond the existing bounded rollback and verification flow

## Temptations To Reject

Reject these design paths even if they appear convenient:

- storing assistant-owned status like "blocked", "resolved", or "recommended next step"
  outside canonical session truth
- persisting chat history as if it were part of incident state
- using the assistant to invent actions not already present in the runtime
- making the first console screen a chat landing page instead of sessions/detail/timeline
- wiring assistant answers directly to action execution instead of the existing approval and
  verification seams

## Implementation Shape

### 1. Assistant backend

Add a thin deterministic assistant adapter module that:

- accepts `session_id` plus one operator prompt
- loads the session through `OperatorConsoleAPI` and `SessionArtifactContext`
- classifies the prompt into a narrow supported capability:
  - current-state explanation
  - recent timeline summary
  - blocked-or-ready explanation
  - approve-vs-deny consequence explanation
  - evidence summary
  - verifier explanation
  - handoff-style summary draft
- returns:
  - assistant answer text
  - supported intent/category
  - canonical source references used
  - an explicit note that the response is derived from current runtime truth

If the prompt falls outside the supported capability set, fail closed with a bounded help response
instead of pretending to be a general assistant.

### 2. Minimal console server

Add a narrow stdlib-backed local console server that:

- serves one HTML page
- serves existing Phase 1 session data via JSON routes
- adds one assistant route scoped to a session

Use `OperatorConsoleAPI` as the backend adapter for the existing session/detail/timeline/approval/
verification/handoff surfaces. Add the assistant route as another thin adapter layer, not a new
controller model.

### 3. Minimal UI integration

Add one panel-first HTML page that keeps the product centered on:

- sessions list
- session detail
- timeline
- approval / deny actions
- verification / handoff actions

Then attach the assistant as a right-side or secondary session pane. The landing surface must stay
session/detail first, not chat first.

### 4. Canonical vs non-canonical handling

Do not persist assistant conversation state in this slice.

The browser may hold ephemeral current-page messages in memory, but the repository should not
write assistant history into checkpoints, transcripts, working memory, or handoff artifacts. This
avoids accidental workflow drift and keeps canonical state explicit.

## Data Flow

1. Console UI selects one `session_id`.
2. UI loads session detail, timeline, verification, and handoff state from the thin console
   routes backed by `OperatorConsoleAPI`.
3. UI sends one assistant request with:
   - `session_id`
   - `prompt`
4. Assistant adapter reconstructs current session truth from:
   - checkpoint
   - transcript events
   - `SessionArtifactContext`
   - existing handoff artifact if present
5. Assistant returns a bounded explanation derived from those canonical artifacts only.

## Files Expected To Change

- new assistant mapping doc
- new runtime assistant adapter
- new runtime console server/static UI files
- CLI help / entrypoint only if needed to launch the minimal console server
- focused unit/integration tests
- small README / usage / demo updates describing the pane honestly

## Verification Plan

- unit tests for intent routing and grounded answers
- unit tests proving assistant responses cite canonical sources and do not mutate workflow state
- server/route tests for the assistant surface
- regression coverage showing `OperatorConsoleAPI`, shell, and CLI still behave as before

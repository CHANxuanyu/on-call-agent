# Layered Memory Design

This repository now has an explicit memory and artifact boundary story for the current milestone.
It is intentionally narrow:

- checkpoints hold resumable control state
- transcripts hold append-only execution truth
- `IncidentWorkingMemory` holds a compact verified semantic snapshot for the active incident
- handoff artifacts are derived operator-facing outputs
- project memory remains intentionally minimal and out of the active runtime flow

The goal of this design is not to build a broad memory platform. The goal is to keep incident
state understandable, replayable, and safe.

## Current Status

Implemented now:

- checkpoint-driven resumability through `SessionCheckpoint`
- append-only transcript events for tool calls, verifier results, permission decisions, and resume
  markers
- `SessionArtifactContext` as the shared read path for verified artifacts plus working-memory
  lookup
- `IncidentWorkingMemory` written on verifier-passed `incident_hypothesis` and
  `incident_recommendation` transitions
- handoff context assembly and stable handoff artifact regeneration from durable state

Intentionally deferred:

- project-memory promotion and cross-incident recall workflows
- background extraction or compaction systems
- using memory as a hidden substitute for transcript or checkpoint truth

## Boundary Table

| Layer | Purpose | Source Of Truth | What Belongs Here | What Does Not |
| --- | --- | --- | --- | --- |
| Checkpoint control state | Track where the harness is and what it is waiting on | `sessions/checkpoints/<session_id>.json` | `current_phase`, `current_step`, pending verifier state, approval state, progress summary | semantic incident conclusions, copied tool outputs, handoff prose dumps |
| Transcript execution truth | Preserve what actually happened | `sessions/transcripts/<session_id>.jsonl` | resume markers, model-step notes, permission decisions, tool requests/results, verifier results, checkpoint markers | mutable summaries that replace prior events |
| Incident working memory | Keep a compact verified semantic snapshot for the active incident | `sessions/working_memory/<incident_id>.json` | leading hypothesis, unresolved gaps, important evidence refs, recommendation summary, compact handoff note | raw transcript history, unverified guesses, permission/verifier payload internals |
| Derived handoff artifact | Produce stable operator-facing output | `sessions/handoffs/<incident_id>.json` | current readable handoff snapshot derived from durable state | control-plane authority or resume state |
| Project memory | Hold slow-moving reusable operational knowledge | local project-memory models only; not part of active flow in this milestone | curated long-lived references when explicitly promoted later | active incident facts, approval state, automatic per-session writes |

## Interaction Model

### Checkpoints

Checkpoints answer control-plane questions:

- which phase is current
- which verifier is still pending
- whether approval is outstanding
- what the latest compact progress summary is

They do not own semantic incident understanding.

### Transcripts

Transcripts remain append-only history. They are the durable execution record used for replay and
artifact reconstruction.

Current event types:

- `resume_started`
- `model_step`
- `permission_decision`
- `tool_request`
- `tool_result`
- `verifier_result`
- `checkpoint_written`

### SessionArtifactContext

`SessionArtifactContext` is the read seam that ties the durable layers together. It:

- loads checkpoint and transcript once
- reconstructs the latest typed artifacts for each implemented slice
- distinguishes verified success, insufficiency, and synthetic failure
- exposes incident working memory read-only for downstream assembly layers

It is a reconstruction layer, not a replacement source of truth.

### IncidentWorkingMemory

`IncidentWorkingMemory` is the first semantic-memory slice. It exists so the runtime does not have
to overload checkpoints with semantic summaries or keep re-deriving every operator-facing summary
from scratch.

For this milestone it is intentionally limited:

- incident-scoped
- verifier-backed
- mutable latest snapshot
- written only on selected verifier-passed transitions

It is not:

- transcript history
- a control-plane checkpoint
- long-lived project memory
- a reason to bypass artifact verification

### Derived Handoff Artifacts

The handoff flow is downstream of the runtime truth layers:

`SessionArtifactContext -> IncidentHandoffContextAssembler -> IncidentHandoffArtifactWriter`

This keeps operator output reproducible while avoiding the mistake of treating handoff artifacts as
resume state.

## Why This Is The Right Stopping Point

This milestone needed one semantic-memory slice to prove that:

- semantic incident understanding can be kept separate from control state
- handoff-oriented assembly can be regenerated from durable runtime artifacts
- the runtime can stay explicit about what is verified, what is pending, and what is only derived

It did not need a broader memory system. Project memory, promotion rules, and cross-incident recall
are intentionally deferred because they add scope faster than they add credibility for the current
runtime milestone.

## Non-Goals

This design does not recommend:

- a generic planner
- hidden prompt-side memory as the primary state mechanism
- auto-writing project memory from every session
- multi-agent memory coordination
- vector-store or retrieval scope expansion for this milestone
- replacing transcript/checkpoint truth with mutable summaries

## Bottom Line

The repository now has a coherent layered memory story for the current milestone:

- checkpoint for control
- transcript for execution truth
- `IncidentWorkingMemory` for current verified incident understanding
- handoff artifacts for stable operator-facing output

That is enough structure to make the runtime auditable, resumable, and explainable without
broadening into product-scale memory machinery.

# Assistant Grounding Plan

## Scope

Tighten the Phase 1.5 assistant grounding contract so it stays aligned with the repository's
architecture summary:

- workflow authority stays with checkpoint control state, append-only transcripts, approval state,
  and verifier-backed artifacts reconstructed through `SessionArtifactContext`
- `IncidentWorkingMemory` and exported handoff artifacts are supporting derived context, not
  workflow authority
- chat remains explicitly non-canonical

## Planned changes

1. Update `src/runtime/assistant_api.py`
   - split assistant grounding references into authoritative workflow sources vs supporting derived
     context
   - revise docstrings and default authority text so the assistant does not imply every source is
     canonical authority
   - keep `working_memory` and `handoff_artifact` in supporting context only

2. Update `src/runtime/console_server.py`
   - adjust the assistant pane grounding label so the UI distinguishes workflow authority from
     supporting context

3. Update `docs/phase15_assistant_mapping.md`
   - make canonical vs supporting derived context explicit and consistent with
     `docs/architecture.md`

4. Update focused tests
   - adapt existing assistant tests to the renamed grounding fields
   - add a regression proving working memory is surfaced as supporting context rather than workflow
     authority
   - keep shell/CLI/runtime behavior unchanged

## Non-goals

- no change to runtime control authority
- no change to shell or CLI semantics
- no change to approval, verifier, or handoff behavior
- no chat persistence or new assistant capabilities

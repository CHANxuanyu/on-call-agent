## Phase 1 API Plan

1. Add one thin runtime adapter module for the Operator Console backend contract.
   It will expose typed read/write functions for:
   - recent sessions list
   - single-session detail
   - transcript / verifier / checkpoint timeline
   - approval / deny action resolution
   - verification result view and explicit verify rerun
   - handoff artifact access
2. Reuse existing durable runtime truth only:
   - checkpoints for control state and operator-shell mode
   - append-only transcripts for timeline and latest verifier/audit state
   - `SessionArtifactContext` for typed artifact reconstruction
   - existing handoff artifacts and regeneration seams
   - existing live approval / verification functions for mutation paths
3. Do not add a second state store, new workflow semantics, or new incident-family behavior.
   Approval and verification semantics must remain exactly the same as the current shell/CLI.
4. Document how each API surface maps to checkpoints, transcripts, verified artifacts, or handoff
   files so future console work can stay grounded in runtime truth.
5. Add focused tests for the new adapter contract and run targeted lint/tests only.

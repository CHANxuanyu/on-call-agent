# Review Scope: Slice 3 - Phase Boundary Tightening

## Objective
Close the remaining Runtime Contract gap by making phase-bearing inputs and outputs explicit, bounded, and phase-aware.

This slice should tighten contract boundaries where phase values control artifact lookup, step progression, verifier inputs, or checkpoint interpretation, while preserving the current durable JSON shape and existing phase vocabulary whenever possible.

## In-Scope
- Review phase-bearing fields that are currently modeled as unbounded strings in checkpoint payloads, verifier input models, runtime models, and trusted artifact lookup inputs.
- Review whether invalid, misspelled, impossible, or cross-phase-incompatible values are rejected before progression.
- Review whether phase-aware validation is explicit at step entrypoints and artifact-consumption boundaries.
- Review whether bounded phase typing can be introduced without changing serialized phase values.
- Review whether inspect/load surfaces handle phase-validation failures conservatively.

## Out-of-Scope
- Broad workflow redesign.
- New phase taxonomy beyond the currently implemented phase vocabulary.
- Verifier framework redesign.
- Persistence-layer redesign.
- Eval harness expansion beyond evidence gathering in this slice.
- UI changes.

## Acceptance Criteria
- Phase-bearing contract fields are bounded by an enum or equivalently strict validator.
- Invalid or impossible phase values are rejected fail-closed before progression or trusted artifact reuse.
- Phase-aware validation is explicit where phase values control resume, lookup, or step execution.
- Durable serialized phase values remain unchanged unless a narrowly justified exception is explicitly approved.
- Completion of this slice is sufficient to mark A.1 as complete.

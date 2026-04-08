# Decisions

## 2026-04-07 | Slice 1 Verifier Architecture Closure
- Decision: close Slice 1 with narrow, auditable changes only.
- Decision: contract validation must be explicit in code through staged verifier structure, using `_verify_contract(...)` followed by `_verify_outcome(...)`.
- Decision: concrete registered verifiers remain categorized as `outcome` verifiers in this slice.
- Decision: separately registered contract-verifier components are intentionally deferred to avoid a broader verifier-framework rewrite before it is needed.
- Decision: preserve durable JSON shape, preserve current phase vocabulary, and keep eval harness scope unchanged for this slice.
- Follow-up: revisit `RVW-S1-03` in Slice 1b / later if bounded phase typing can be introduced with truly zero replay/checkpoint churn.

## 2026-04-08 | Slice 2 Checkpoint / Resume Semantics Closure
- Decision: close Slice 2 with narrow, auditable seam fixes only; no checkpoint/transcript/artifact framework rewrite and no new large phase taxonomy.
- Decision: the latest committed checkpoint truth is the loaded checkpoint file only when it matches the trusted `checkpoint_written` transcript marker for that checkpoint. Trusted artifact reconstruction uses only the transcript prefix through that marker.
- Decision: transcript events after the committed checkpoint boundary are an explicit uncommitted tail. The runtime classifies that tail as `clean`, `visible_non_resumable`, or `unsafe`; unsafe tails fail closed and visible tails remain inspectable but non-resumable.
- Decision: `verifier_request` is the transcript-backed durable truth for in-flight verifier execution and verifier interruption. This closes the interrupted-verifier seam without introducing pre-verifier checkpoint churn.
- Decision: `pending_verifier` remains committed post-verifier control state only. It is not an in-flight marker and is only written into committed checkpoints after a non-`PASS` verifier result.
- Decision: read-only vs write-capable tail safety classification must come from explicit tool risk metadata in transcript events or stable tool definitions, never from tool-name guessing.
- Follow-up: older historical transcripts remain readable but do not retroactively gain `verifier_request`, so pre-Slice-2 verifier interruption diagnosis remains less precise.

## 2026-04-08 | Slice 3 Phase Boundary Tightening Closure
- Decision: close Slice 3 with narrow contract tightening only. Preserve the current runtime narrative, avoid broad phase-taxonomy redesign, and keep serialized phase values unchanged.
- Decision: `IncidentPhase` is the bounded central vocabulary for the currently implemented true phase-bearing contract fields only. It applies to durable checkpoint phase truth, working-memory phase provenance, verifier phase inputs, and structured operator/handoff surfaces that carry current phase as contract state.
- Decision: `invalid phase` means unknown, typoed, or out-of-vocabulary input and is always a fail-closed contract/load rejection.
- Decision: `valid but incompatible phase` means an in-vocabulary phase that is not allowed for a specific runtime boundary. This remains an ordinary runtime incompatibility only where that behavior is intentionally preserved.
- Decision: verifier boundaries are stricter than runtime artifact reuse. A globally valid but wrong-family phase is verifier-contract-invalid for that verifier and must fail during verifier input validation.
- Decision: wrong-step runtime entry now fails closed before any new transcript or checkpoint writes. The runtime must not normalize wrong-family entry into later deferred checkpoints.
- Decision: artifact/runtime boundaries may still return explicit incompatible or insufficient runtime results for valid in-vocabulary phases only where that tolerance is intentionally preserved and narrow.
- Decision: intentionally unchanged scope remains explicit: no phase taxonomy redesign, no serialized value changes, and display-only `previous_phase` echoes may remain string-shaped where they are not true contract fields.

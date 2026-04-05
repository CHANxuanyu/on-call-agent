# 1. Design summary

Successful recovery now has an explicit durable-state transition. On verifier-passed `outcome_verification_succeeded`, [deployment_outcome_verification.py](/home/chan/projects/on-call-agent/src/agent/deployment_outcome_verification.py) rewrites incident working memory with the current phase, removes the canonical rollback-confirmation gap, and carries forward the verified hypothesis/recommendation plus rollback/probe evidence. [handoff.py](/home/chan/projects/on-call-agent/src/context/handoff.py) now prefers current-phase working memory for unresolved gaps and also treats a verifier-passed outcome phase as resolved on transcript-only fallback. Recommendation wording in [incident_recommendation.py](/home/chan/projects/on-call-agent/src/tools/implementations/incident_recommendation.py) stays distinct from the action stub, and rollback permission events still classify the write tool as `ask` while making the already-recorded approval context explicit in [deployment_rollback_execution.py](/home/chan/projects/on-call-agent/src/agent/deployment_rollback_execution.py) and [inspect.py](/home/chan/projects/on-call-agent/src/runtime/inspect.py).

# 2. What changed

- Outcome verification now writes a fresh working-memory snapshot only on verifier `PASS`, with `source_phase=outcome_verification_succeeded`, `last_updated_by_step=deployment_outcome_verification`, cleared stale rollback-validation gap, appended rollback/probe evidence refs, and a resolved compact note.
- The canonical supported-hypothesis unresolved gap was factored into a shared constant in [incident_hypothesis.py](/home/chan/projects/on-call-agent/src/tools/implementations/incident_hypothesis.py) so the resolved-state writer removes the exact durable gap rather than blindly hiding it.
- Recommendation text now means rollback-readiness validation, not an action candidate. The action stub still proposes the rollback candidate, and execution still performs the approved rollback.
- The rollback execution permission record still uses `action=ask`, but its stored `reason`, `approval_reason`, and notes now say approval was already recorded and execution is proceeding within the reviewed rollback scope.
- Audit summaries for `permission_decision` events now surface that clearer post-approval message for `ask` events.
- Added regressions for resolved working memory, resolved handoff assembly, and clearer post-approval audit output.

# 3. Why this is safe

The durable-state rewrite only happens after outcome verification passes, so unresolved gaps are not cleared on mere approval or rollback execution. It removes only the canonical rollback-validation gap, leaving any unrelated gaps intact. Serialized enum values and replay/eval contracts stay unchanged, and the write tool remains approval-gated by policy with the same `action=ask` classification.

# 4. Files touched

- [src/tools/implementations/incident_hypothesis.py](/home/chan/projects/on-call-agent/src/tools/implementations/incident_hypothesis.py)
- [src/tools/implementations/incident_recommendation.py](/home/chan/projects/on-call-agent/src/tools/implementations/incident_recommendation.py)
- [src/tools/implementations/incident_action_stub.py](/home/chan/projects/on-call-agent/src/tools/implementations/incident_action_stub.py)
- [src/agent/incident_recommendation.py](/home/chan/projects/on-call-agent/src/agent/incident_recommendation.py)
- [src/agent/deployment_rollback_execution.py](/home/chan/projects/on-call-agent/src/agent/deployment_rollback_execution.py)
- [src/agent/deployment_outcome_verification.py](/home/chan/projects/on-call-agent/src/agent/deployment_outcome_verification.py)
- [src/context/handoff.py](/home/chan/projects/on-call-agent/src/context/handoff.py)
- [src/runtime/inspect.py](/home/chan/projects/on-call-agent/src/runtime/inspect.py)
- [tests/integration/test_handoff_context_assembly.py](/home/chan/projects/on-call-agent/tests/integration/test_handoff_context_assembly.py)
- [tests/integration/test_live_deployment_regression_cli.py](/home/chan/projects/on-call-agent/tests/integration/test_live_deployment_regression_cli.py)
- [tests/integration/test_incident_working_memory_flow.py](/home/chan/projects/on-call-agent/tests/integration/test_incident_working_memory_flow.py)
- [tests/unit/test_handoff_context.py](/home/chan/projects/on-call-agent/tests/unit/test_handoff_context.py)
- [tests/unit/test_runtime_inspect.py](/home/chan/projects/on-call-agent/tests/unit/test_runtime_inspect.py)

# 5. Invariants preserved

- `validate_recent_deployment` and `rollback_recent_deployment_candidate` serialized values are unchanged.
- Recommendation, action stub, and execution remain separate layers.
- Write execution still requires an already-recorded approval and remains policy-classified as `ask`.
- Checkpoint, transcript, verifier-gated progression, and `SessionArtifactContext` recovery seams were not redesigned.
- Replay/eval stage order and inspection/handoff surfaces remain intact.

# 6. Verification performed

- `ruff check src/tools/implementations/incident_hypothesis.py src/tools/implementations/incident_recommendation.py src/tools/implementations/incident_action_stub.py src/agent/incident_recommendation.py src/agent/deployment_rollback_execution.py src/agent/deployment_outcome_verification.py src/context/handoff.py src/runtime/inspect.py tests/integration/test_handoff_context_assembly.py tests/integration/test_live_deployment_regression_cli.py tests/integration/test_incident_working_memory_flow.py tests/unit/test_handoff_context.py tests/unit/test_runtime_inspect.py`
- `pytest tests/integration/test_live_deployment_regression_cli.py tests/integration/test_handoff_context_assembly.py tests/integration/test_incident_working_memory_flow.py tests/integration/test_incident_chain_replay_eval.py tests/integration/test_runtime_eval_cli.py tests/unit/test_handoff_context.py tests/unit/test_runtime_inspect.py tests/unit/test_incident_recommendation_tool.py tests/unit/test_incident_action_stub_tool.py tests/unit/test_incident_recommendation_verifier.py tests/unit/test_incident_action_stub_verifier.py tests/unit/test_action_approval_gate_contract.py tests/unit/test_runtime_cli.py`
- Result: `37 passed, 2 skipped`
- The 2 skipped tests are the live socket CLI tests, skipped here because local TCP bind is unavailable in this sandbox; equivalent non-network regressions were added for the resolved-state and audit semantics.

# 7. Remaining risks

- The end-to-end live demo-target assertions in [test_live_deployment_regression_cli.py](/home/chan/projects/on-call-agent/tests/integration/test_live_deployment_regression_cli.py) were skipped in this environment, so that exact path should still be run where `127.0.0.1` binding is available.
- The legacy enum name `validate_recent_deployment` still carries some semantic ambiguity by design; the behavior is clearer now, but the serialized label remains a compatibility artifact.

# 8. Suggested commit message

`Polish resolved recovery state and clarify post-approval rollback audit semantics`

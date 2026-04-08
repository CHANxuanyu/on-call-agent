# Full System Mastery Guide Plan

## Goal

Create two repository-grounded mastery guides:

- `docs/full_system_mastery_guide_en.md`
- `docs/full_system_mastery_guide_zh.md`

The guides should be the most complete learning documents in the repository for someone who wants
to truly understand the current system, without overselling scope or inventing capabilities.

## Grounding Rules

The guides must stay anchored to:

- current implementation under `src/`
- current tests under `tests/`
- current product/runtime docs
- current honest scope in `README.md`, `AGENTS.md`, `docs/architecture.md`, and
  `docs/product/PRODUCT_BRIEF.md`

The guides must preserve these truths:

- verifier-driven progression
- durable checkpoint and transcript state
- approval-gated risky execution
- one bounded `deployment-regression` live path today
- not a coding agent
- not a mature ops product
- not broad autonomous remediation

## Sources Inspected

### Core docs

- `README.md`
- `AGENTS.md`
- `docs/architecture.md`
- `docs/usage.md`
- `docs/demo.md`
- `docs/project_summary.md`
- `docs/interview_mastery_guide.md`
- `docs/layered_memory_design.md`
- `docs/claude_code_comparison.md`
- `docs/operator_shell_smoke_checklist.md`
- `docs/product/PRODUCT_BRIEF.md`

### Core runtime and state code

- `src/agent/*.py`
- `src/context/*.py`
- `src/evals/incident_chain_replay.py`
- `src/memory/*.py`
- `src/permissions/*.py`
- `src/runtime/*.py`
- `src/skills/*.py`
- `src/tools/*.py`
- `src/transcripts/*.py`
- `src/verifiers/*.py`
- `skills/incident-triage/SKILL.md`
- `docs/examples/deployment_regression_payload.json`
- `evals/fixtures/*.json`
- `sessions/schema/checkpoint-v1.example.json`
- `pyproject.toml`

### Behavioral contract tests

- integration:
  `test_live_deployment_regression_cli.py`,
  `test_runtime_shell_cli.py`,
  `test_runtime_console_api.py`,
  `test_incident_chain_replay_eval.py`,
  `test_session_artifact_context.py`,
  `test_handoff_context_assembly.py`,
  `test_handoff_regeneration_flow.py`,
  `test_incident_working_memory_flow.py`
- unit:
  `test_permission_policy.py`,
  `test_action_approval_gate_contract.py`,
  `test_runtime_execution.py`,
  `test_runtime_inspect.py`,
  `test_resumable_slice_harness.py`,
  `test_runtime_assistant_api.py`,
  `test_runtime_shell.py`,
  `test_runtime_console_server.py`

## Coverage Checklist

Both guides must cover:

1. what the repository is
2. what it is not
3. product framing vs runtime framing
4. repository map
5. end-to-end incident chain
6. runtime truth and state model
7. operator surfaces
8. live deployment-regression path
9. safety model
10. key code walkthrough
11. how to run and inspect the project
12. current limitations
13. how to explain the project in interviews
14. recommended study path

## Structure Plan

Use the same section order in English and Chinese:

1. Executive Truth
2. What The Repository Is And Is Not
3. Product Framing vs Runtime Framing
4. Current Scope Snapshot
5. Repository Map
6. End-to-End Incident Chain
7. Runtime Truth and State Model
8. Operator Surfaces
9. Live Deployment-Regression Path
10. Safety Model
11. Key Code Walkthrough
12. How To Run, Inspect, and Verify
13. What The Tests Prove
14. Current Limitations
15. Interview Framing
16. Recommended Study Path
17. Bottom Line

## Alignment Rules For English and Chinese

- Keep the same section ordering.
- Keep the same core claims and caveats.
- Keep code identifiers, phase names, tool names, verifier names, and file paths in English
  monospace form.
- Translate explanation prose, not code identifiers.
- Do not add claims in one language that do not appear in the other.
- Preserve the same safety and scope language in both versions.

## Specific Repository Truth To Emphasize

- The runtime chain is explicit, not a broad agent planner.
- `IncidentTriageStep` is the special first slice; later slices resume from durable state.
- `SessionArtifactContext` is the shared reconstruction seam for durable artifacts.
- `IncidentWorkingMemory` is supplementary semantic memory, not resume truth.
- handoff artifacts are derived outputs, not workflow authority.
- the console, shell, CLI, and assistant reuse the same runtime truth.
- the assistant pane is session-scoped, bounded, and secondary.
- `auto-safe` is fail-closed and bounded to the current rollback slice.
- the replay path stops at the action stub; the live path continues only for the approved bounded
  rollback flow.

## Quality Bar

The new guides should be more comprehensive than `docs/architecture.md` by adding:

- clearer product-vs-runtime framing
- a broader repository map
- a more explicit walkthrough of operator surfaces
- a fuller explanation of live-path mechanics
- a stronger treatment of tests as runtime truth
- run/inspect/demo instructions in one place
- interview framing and study sequencing

## Completion Checklist

- [x] inspect docs
- [x] inspect relevant runtime code
- [x] inspect relevant tests
- [x] create plan doc
- [x] create English mastery guide
- [x] create Chinese mastery guide
- [x] sanity-check semantic alignment and repository grounding

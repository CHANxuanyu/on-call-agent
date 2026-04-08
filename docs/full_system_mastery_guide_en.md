# Full System Mastery Guide (English)

This is the most comprehensive repository-grounded guide for mastering this project as it exists
today. It is intentionally stricter than a marketing document: every major claim below is aligned
with current docs, code, and tests.

## 1. Executive Truth

If you remember only one sentence, remember this:

`on-call-agent` is a verifier-driven, durable, approval-gated incident-response runtime for
`On-Call Copilot`, with one honest bounded live path today for the `deployment-regression`
incident family.

If you remember three things, remember these:

1. The repository is about runtime discipline, not breadth.
2. Completion is verifier-driven, not model-declared.
3. The only live write path today is one bounded rollback against a local demo target after
   explicit approval.

## 2. What The Repository Is And Is Not

### What it is

- A Python 3.11+ incident-response harness with typed tools, typed verifiers, checkpoints,
  transcripts, working memory, and handoff artifacts.
- The current runtime foundation for the product direction called `On-Call Copilot`.
- A narrow system that proves resume, audit, verification, approval, and handoff seams before
  claiming broader automation.
- A repo that already contains an operator shell, a minimal panel-first console, replay/eval
  coverage, and one live deployment-regression closed loop.

### What it is not

- Not a coding agent.
- Not a generic chatbot.
- Not a generic planner.
- Not a mature ops product.
- Not a broad autonomous remediation platform.
- Not a multi-agent system.
- Not a general-purpose orchestration engine with arbitrary incident families and action libraries.

## 3. Product Framing vs Runtime Framing

This repository has two equally important lenses, and confusing them leads to bad explanations.

### Product framing

Per `docs/product/PRODUCT_BRIEF.md`, `On-Call Copilot` is:

- an operator-facing incident decision and verification product
- meant to help an on-call engineer inspect current state, review a bounded mitigation candidate,
  verify whether it worked, and export a handoff
- intentionally narrow and honest about its maturity

Product value is not "AI can do ops." Product value is decision compression:

- What is happening?
- What evidence supports the current belief?
- Is there a bounded action candidate?
- Does it need approval?
- Did recovery actually happen?
- Can the next operator resume safely?

### Runtime framing

The runtime is the stronger technical story today. The codebase is a:

- verifier-driven state machine over a narrow incident chain
- checkpoint-plus-transcript durable runtime
- approval-aware system with explicit permission provenance
- replayable and inspectable harness

The product surface is thin on purpose. The runtime truth stays in durable artifacts, not in UI
state or assistant chat history.

### The practical rule

When talking about this repo:

- use product language for operator experience
- use runtime language for implementation truth
- never let product claims outrun implemented runtime behavior

## 4. Current Scope Snapshot

| Area | Current Truth | Not True Yet |
| --- | --- | --- |
| Incident family | `deployment-regression` is the one live family | broad multi-family incident support |
| Live write path | one bounded rollback to the known-good version | arbitrary remediation actions |
| Live target | local demo HTTP service in `src/runtime/demo_target.py` | real production integrations |
| Read path | deterministic triage through action stub | open-ended investigation planner |
| Operator surfaces | direct CLI, shell, console, session assistant | mature multi-user product workflow |
| State model | checkpoints, transcripts, working memory, handoff artifacts | hidden UI-side workflow state |
| Autonomy | `manual`, `semi-auto`, fail-closed `auto-safe` | broad autonomous ops execution |
| Eval scope | two deterministic replay scenarios | broad benchmark harness |
| Skill system | repository skill asset loading, used by triage | a broad library of operational skills |
| LLM dependence on critical path | no model-backed free-form runtime loop is required for the current slice | general LLM agent orchestration |

## 5. Repository Map

### Top-level map

| Path | Why it matters |
| --- | --- |
| `README.md` | best short project framing and quickstart |
| `AGENTS.md` | architectural and product discipline rules for the repo |
| `docs/architecture.md` | core runtime architecture summary |
| `docs/usage.md` | command reference for CLI, shell, and console |
| `docs/demo.md` | fastest live demo walkthrough |
| `docs/product/PRODUCT_BRIEF.md` | controlling product spec for `On-Call Copilot` |
| `skills/incident-triage/SKILL.md` | concrete example of repository-managed skill metadata plus instructions |
| `src/` | actual runtime implementation |
| `tests/` | current behavioral contract |
| `evals/fixtures/` | deterministic replay fixtures |
| `sessions/` | durable runtime outputs and examples |
| `docs/examples/deployment_regression_payload.json` | canonical live demo intake payload |

### Source map by subsystem

| Subsystem | Key files | Responsibility |
| --- | --- | --- |
| Step chain | `src/agent/incident_*.py` | explicit investigation and action-candidate slices |
| Live execution | `src/agent/deployment_rollback_execution.py`, `src/agent/deployment_outcome_verification.py` | approved rollback and post-action verification |
| Tools | `src/tools/implementations/*.py` | deterministic read/write tool behavior |
| Verifiers | `src/verifiers/implementations/*.py` | pass/fail rules for each slice |
| Context reconstruction | `src/context/session_artifacts.py` | rebuild latest usable artifacts from checkpoint and transcript |
| Handoff | `src/context/handoff*.py` | assemble, write, and regenerate operator handoff output |
| Durable state | `src/memory/checkpoints.py`, `src/memory/incident_working_memory.py`, `src/transcripts/*.py` | checkpoints, working memory, append-only transcript storage |
| Permissions | `src/permissions/*.py` | allow/ask/deny policy and provenance |
| Shell | `src/runtime/shell.py` | terminal operator workspace |
| Console | `src/runtime/console_api.py`, `src/runtime/console_server.py` | thin panel-first console over runtime truth |
| Assistant pane | `src/runtime/assistant_api.py` | bounded session explainer, not workflow authority |
| Inspect/export | `src/runtime/inspect.py` | session, artifact, audit, and export views |
| CLI | `src/runtime/cli.py` | direct command entrypoint |
| Live surface | `src/runtime/live_surface.py` | start incident, resolve approval, rerun verification |
| Replay/eval | `src/evals/incident_chain_replay.py`, `src/runtime/eval_surface.py` | deterministic replay runner and summaries |
| Demo target | `src/runtime/demo_target.py` | local service with `/deployment`, `/health`, `/metrics`, `/rollback` |

## 6. End-to-End Incident Chain

### Two honest paths

Replay and pre-approval runtime:

`triage -> follow-up -> evidence -> hypothesis -> recommendation -> approval-gated action stub`

Live approved deployment-regression runtime:

`triage -> follow-up -> evidence -> hypothesis -> recommendation -> approval-gated action stub -> bounded rollback execution -> outcome verification`

### Slice-by-slice walkthrough

| Stage | Main file | Tool | Verifier | Success phase | Durable effect |
| --- | --- | --- | --- | --- | --- |
| Triage | `src/agent/incident_triage.py` | `incident_payload_summary` | `incident_triage_output` | `triage_completed` | creates first transcript and first checkpoint |
| Follow-up | `src/agent/incident_follow_up.py` | `investigation_focus_selector` | `incident_follow_up_outcome` | `follow_up_investigation_selected` or `follow_up_complete_no_action` | resumes from triage artifacts and chooses one target or safe no-op |
| Evidence | `src/agent/incident_evidence.py` | `evidence_bundle_reader` | `incident_evidence_read_outcome` | `evidence_reading_completed` | reads one live or fixture-backed evidence bundle |
| Hypothesis | `src/agent/incident_hypothesis.py` | `incident_hypothesis_builder` | `incident_hypothesis_outcome` | `hypothesis_supported` or `hypothesis_insufficient_evidence` | writes first `IncidentWorkingMemory` snapshot on verifier pass |
| Recommendation | `src/agent/incident_recommendation.py` | `incident_recommendation_builder` | `incident_recommendation_outcome` | `recommendation_supported` or `recommendation_conservative` | updates `IncidentWorkingMemory` with recommendation-level state |
| Action stub | `src/agent/incident_action_stub.py` | `incident_action_stub_builder` | `incident_action_stub_outcome` | `action_stub_pending_approval` or `action_stub_not_actionable` | writes durable `approval_state` boundary |
| Rollback execution | `src/agent/deployment_rollback_execution.py` | `deployment_rollback_executor` | `deployment_rollback_execution` | `action_execution_completed` | performs one bounded write after recorded approval |
| Outcome verification | `src/agent/deployment_outcome_verification.py` | `deployment_outcome_probe` | `deployment_outcome_verification` | `outcome_verification_succeeded` | verifies recovery from external runtime state and rewrites working memory with resolved state |

### Why the chain matters

This is not a generic planner loop. Each slice:

1. consumes one prior durable artifact
2. emits transcript events
3. runs a verifier
4. writes the next checkpointed phase

That is the core mastery concept of the repo.

### Phase vocabulary you should know

Most important phases:

- `triage_completed`
- `follow_up_investigation_selected`
- `follow_up_complete_no_action`
- `evidence_reading_completed`
- `hypothesis_supported`
- `hypothesis_insufficient_evidence`
- `recommendation_supported`
- `recommendation_conservative`
- `action_stub_pending_approval`
- `action_stub_not_actionable`
- `action_stub_approved`
- `action_stub_denied`
- `action_execution_completed`
- `outcome_verification_succeeded`

Important failure/deferred phases:

- `*_unverified`
- `*_failed_verification`
- `*_failed_artifacts`
- `evidence_reading_deferred`
- `hypothesis_deferred`
- `recommendation_deferred`
- `action_stub_deferred`
- `action_execution_deferred`

If you can read a checkpoint phase and immediately explain what it means operationally, you are
already past the beginner stage.

## 7. Runtime Truth and State Model

The repository has a deliberately layered state model.

### Layer 1: checkpoint control state

Stored in:

- `sessions/checkpoints/<session_id>.json`

Defined in:

- `src/memory/checkpoints.py`

What it answers:

- where the runtime is now
- what phase it is in
- what step number it reached
- whether approval is pending/approved/denied
- what verifier is still pending
- what requested/effective shell mode is active

Important fields:

- `current_phase`
- `current_step`
- `pending_verifier`
- `approval_state`
- `operator_shell`
- `summary_of_progress`

What does not belong here:

- full execution history
- full semantic incident understanding
- handoff prose as workflow authority

### Layer 2: transcript execution truth

Stored in:

- `sessions/transcripts/<session_id>.jsonl`

Defined in:

- `src/transcripts/models.py`
- `src/transcripts/writer.py`

Current event types:

- `resume_started`
- `model_step`
- `permission_decision`
- `tool_request`
- `tool_result`
- `verifier_result`
- `checkpoint_written`
- `approval_resolved`

What it answers:

- what actually happened
- in what order
- which tool/verifier calls ran
- whether a path contains missing results or structured failures

Why append-only matters:

- replayability
- auditability
- postmortem readability
- artifact reconstruction without trusting in-memory state

### Layer 3: semantic incident memory

Stored in:

- `sessions/working_memory/<incident_id>.json`

Defined in:

- `src/memory/incident_working_memory.py`

Current role:

- compact verifier-backed semantic snapshot
- written on verifier-passed `incident_hypothesis`, `incident_recommendation`, and successful
  `deployment_outcome_verification`

Typical contents:

- leading hypothesis snapshot
- unresolved gaps
- important evidence references
- recommendation snapshot
- compact handoff note

What it is not:

- resume source of truth
- transcript replacement
- project memory

### Layer 4: derived handoff artifact

Stored in:

- `sessions/handoffs/<incident_id>.json`

Defined in:

- `src/context/handoff.py`
- `src/context/handoff_artifact.py`
- `src/context/handoff_regeneration.py`

Role:

- stable operator-facing export derived from durable runtime truth

Not a role:

- workflow authority
- resume state

### `SessionArtifactContext`: the key reconstruction seam

Defined in:

- `src/context/session_artifacts.py`

This is one of the most important files in the repo. It:

- loads checkpoint and transcript once
- reconstructs latest typed outputs for triage, follow-up, evidence, hypothesis,
  recommendation, action stub, action execution, and outcome verification
- exposes verified vs latest forms
- exposes `IncidentWorkingMemory` read-only
- distinguishes availability, insufficiency, and failure

If you do not understand `SessionArtifactContext`, you do not fully understand the repo.

### Insufficiency vs synthetic failure

This distinction is central.

Insufficiency means:

- the runtime is conservatively not ready yet
- example: phase is incompatible with a later slice
- example: verifier has not passed

Synthetic failure means:

- the runtime expected a durable artifact path and found something broken
- example: tool request exists but no tool result was ever recorded
- example: transcript output fails typed validation
- example: checkpoint implies a verifier-backed artifact, but verifier result is missing

Synthetic failures are typed in `src/runtime/models.py` and normalized in
`src/runtime/execution.py`.

## 8. Operator Surfaces

All operator surfaces sit over the same runtime truth.

### Direct CLI

Primary commands from `src/runtime/cli.py`:

- `start-incident`
- `resolve-approval`
- `verify-outcome`
- `inspect-session`
- `inspect-artifacts`
- `show-audit`
- `export-handoff`
- `list-evals`
- `run-eval`
- `run-demo-target`
- `console`
- `shell`

The CLI is the thinnest surface over the runtime seams.

### Operator Shell

Implemented in:

- `src/runtime/shell.py`

Commands:

- `/sessions`
- `/new`
- `/resume`
- `/mode`
- `/status`
- `/inspect`
- `/audit`
- `/tail`
- `/why-not-auto`
- `/approve`
- `/deny`
- `/verify`
- `/handoff`

Modes:

- `manual`
- `semi-auto`
- `auto-safe`

The shell does not create a second orchestration runtime. It calls the same live surface and
inspection/export seams as the CLI.

### Operator Console

Implemented in:

- `src/runtime/console_api.py`
- `src/runtime/console_server.py`

Important truth:

- the console is panel-first, not chat-first
- the UI exposes sessions, incident detail, timeline, approval, verification, and handoff
- it talks to `/api/phase1`

### Session Assistant Pane

Implemented in:

- `src/runtime/assistant_api.py`

This is a bounded explainer, not a general agent:

- session-scoped
- grounded in checkpoint, transcript, `SessionArtifactContext`, and handoff state
- does not persist chat history
- does not become workflow authority
- intentionally fails closed on generic planner prompts

Tests explicitly confirm those boundaries in `tests/unit/test_runtime_assistant_api.py`.

## 9. Live Deployment-Regression Path

### Demo target

The live demo target is implemented in `src/runtime/demo_target.py`.

Endpoints:

- `GET /deployment`
- `GET /health`
- `GET /metrics`
- `POST /rollback`

Initial demo state:

- current version = bad version, default `2.1.0`
- previous version = known-good version, default `2.0.9`
- health is degraded
- rollback is available

After rollback:

- current version becomes previous version
- health becomes healthy
- metrics improve

### Live intake payload

The canonical example is `docs/examples/deployment_regression_payload.json`.

Critical fields:

- `service_base_url`
- `expected_bad_version`
- `expected_previous_version`

Those fields are what make the live bounded rollback path possible.

### Live path mechanics

1. `start-incident` reads the payload and runs triage, follow-up, evidence, hypothesis,
   recommendation, and action stub.
2. If evidence supports deployment regression, the session stops at
   `action_stub_pending_approval`.
3. `resolve-approval --decision approve` records approval durably, then runs:
   - `DeploymentRollbackExecutionStep`
   - `DeploymentOutcomeVerificationStep`
4. `verify-outcome` can rerun outcome verification later.

### What the bounded rollback actually checks

The rollback tool in `src/tools/implementations/deployment_rollback.py` validates:

- action stub type is `rollback_recent_deployment_candidate`
- live deployment still reports an active bad release
- rollback is still available
- live current version still matches `expected_bad_version`
- live previous version still matches `expected_previous_version`

This is not "execute arbitrary remediation." It is one tightly scoped write.

### What outcome verification actually checks

The post-action verifier in `src/verifiers/implementations/deployment_outcome_probe.py` requires:

- service is healthy
- `error_rate <= 0.05`
- `timeout_rate <= 0.05`
- if provided, `current_version == expected_previous_version`

Only then does the phase become `outcome_verification_succeeded`.

### `auto-safe` is deliberately narrow

The shell can auto-execute only when all of these hold:

- policy enabled in `.oncall/settings.toml`
- target base URL allowlisted
- session is at pending approval boundary
- verified hypothesis, recommendation, and action stub exist
- hypothesis is supported deployment regression
- recommendation is `validate_recent_deployment`
- action stub is the bounded rollback candidate
- incident working memory exists
- no blocking unresolved gaps remain except the validation gap that the rollback is meant to clear
- live current version matches expected bad version
- live previous version matches expected known-good version
- live deployment endpoint still reports active bad release and rollback available
- rollback has not already been executed

Otherwise `auto-safe` degrades to `semi-auto` and records the downgrade reason durably.

## 10. Safety Model

### Tool risk model

Defined in `src/tools/models.py`:

- `read_only`
- `write`
- `dangerous`

### Permission policy

Defined in `src/permissions/policy.py`:

- read-only tools -> `allow`
- write tools -> `ask`
- dangerous tools -> `deny`

This policy is intentionally simple, but it produces rich provenance:

- policy source
- action category
- evaluated action type
- approval requirement
- approval reason or denial reason
- safety boundary
- future preconditions
- notes

### Approval model

Approval is stored durably in checkpoint `approval_state`.

Key statuses:

- `none`
- `pending`
- `approved`
- `denied`

Important point:

- the action stub records a candidate and approval boundary
- candidacy is not execution

### Post-approval write semantics

One subtle but important detail:

- `deployment_rollback_executor` remains a write tool classified as `ask`
- after approval is already recorded, the runtime rewrites the permission record to explain that
  policy classification still applies, but this is not a fresh approval request

Tests in `tests/unit/test_runtime_inspect.py` and
`tests/integration/test_live_deployment_regression_cli.py` lock this behavior in.

### Conservative behavior is a feature

The system intentionally stays conservative when:

- evidence is insufficient
- live service is already healthy on the known-good version
- approval is denied
- `auto-safe` gate conditions fail
- prior durable artifacts are missing or inconsistent

That is part of the repository's credibility, not a missing feature.

## 11. Key Code Walkthrough

### 1. Intake and first durable slice

- `src/agent/incident_triage.py`

Why it matters:

- it is the special first slice
- it loads the `incident-triage` skill asset
- it writes the first transcript and checkpoint directly

### 2. Resumable chain progression

- `src/agent/incident_follow_up.py`
- `src/agent/incident_evidence.py`
- `src/agent/incident_hypothesis.py`
- `src/agent/incident_recommendation.py`
- `src/agent/incident_action_stub.py`

Why it matters:

- these files show how the repo advances from verified prior artifacts instead of from hidden
  memory

### 3. Shared harness and failure normalization

- `src/runtime/harness.py`
- `src/runtime/execution.py`
- `src/runtime/models.py`

Why it matters:

- common downstream wiring lives here
- tool/verifier failures are normalized into synthetic failures
- later slices stay explicit while shared mechanics are deduplicated

### 4. Live execution seam

- `src/runtime/live_surface.py`
- `src/agent/deployment_rollback_execution.py`
- `src/agent/deployment_outcome_verification.py`

Why it matters:

- this is the only live closed loop past the approval boundary

### 5. Artifact reconstruction and handoff

- `src/context/session_artifacts.py`
- `src/context/handoff.py`
- `src/context/handoff_artifact.py`
- `src/context/handoff_regeneration.py`

Why it matters:

- this is how resume, inspection, and handoff stay consistent without inventing a second state
  layer

### 6. Operator surfaces

- `src/runtime/inspect.py`
- `src/runtime/shell.py`
- `src/runtime/console_api.py`
- `src/runtime/console_server.py`
- `src/runtime/assistant_api.py`

Why it matters:

- these files show the product layer sitting on top of runtime truth rather than replacing it

### 7. Tools and verifiers

Read them in pairs:

- `src/tools/implementations/incident_triage.py`
  with `src/verifiers/implementations/incident_triage.py`
- `src/tools/implementations/follow_up_investigation.py`
  with `src/verifiers/implementations/follow_up_investigation.py`
- `src/tools/implementations/evidence_reading.py`
  with `src/verifiers/implementations/evidence_reading.py`
- `src/tools/implementations/incident_hypothesis.py`
  with `src/verifiers/implementations/incident_hypothesis.py`
- `src/tools/implementations/incident_recommendation.py`
  with `src/verifiers/implementations/incident_recommendation.py`
- `src/tools/implementations/incident_action_stub.py`
  with `src/verifiers/implementations/incident_action_stub.py`
- `src/tools/implementations/deployment_rollback.py`
  with `src/verifiers/implementations/deployment_rollback_execution.py`
- `src/tools/implementations/deployment_outcome_probe.py`
  with `src/verifiers/implementations/deployment_outcome_probe.py`

This pairing makes the verifier-driven architecture obvious.

## 12. How To Run, Inspect, and Verify

### Install

```bash
python -m pip install -e '.[dev]'
```

Fallback if the entrypoint is not on your path:

```bash
.venv/bin/python -m runtime.cli <command> ...
```

### Run the live demo

Start the demo target:

```bash
oncall-agent run-demo-target --port 8001
```

Start the incident:

```bash
oncall-agent start-incident \
  --family deployment-regression \
  --payload docs/examples/deployment_regression_payload.json \
  --json
```

Approve the rollback:

```bash
oncall-agent resolve-approval <session_id> --decision approve --json
```

Rerun verification:

```bash
oncall-agent verify-outcome <session_id> --json
```

Export handoff:

```bash
oncall-agent export-handoff <session_id>
```

### Use the shell

```bash
oncall-agent shell
```

Recommended live flow:

```text
/sessions
/mode semi-auto
/new docs/examples/deployment_regression_payload.json
/status
/why-not-auto
/approve Rollback approved for the live demo target.
/verify
/handoff
```

### Use the console

```bash
oncall-agent console
```

### Run replay/eval

Supported branch:

```bash
oncall-agent run-eval incident-chain-replay-recent-deployment --json
```

Conservative branch:

```bash
oncall-agent run-eval incident-chain-replay-insufficient-evidence --json
```

### Inspect outputs

Session summary:

```bash
oncall-agent inspect-session <session_id>
```

Artifact chain:

```bash
oncall-agent inspect-artifacts <session_id>
```

Audit trail:

```bash
oncall-agent show-audit <session_id> --event-type verifier_result --limit 5
```

### Know where files go

Default live roots:

- `sessions/checkpoints/`
- `sessions/transcripts/`
- `sessions/working_memory/`
- `sessions/handoffs/`

Default eval root:

- `sessions/evals/`

### The fastest files to open after a run

- session checkpoint JSON
- session transcript JSONL
- incident working memory JSON
- handoff JSON

If you can trace one session through those four artifacts, you understand the repo much better.

## 13. What The Tests Prove

### Live closed loop

- `tests/integration/test_live_deployment_regression_cli.py`

Proves:

- start incident reaches `action_stub_pending_approval`
- approval triggers bounded rollback
- outcome verification succeeds
- working memory is rewritten with resolved state
- permission record still explains post-approval write semantics honestly

### Shell behavior

- `tests/integration/test_runtime_shell_cli.py`
- `tests/unit/test_runtime_shell.py`

Proves:

- `semi-auto` reaches the approval boundary
- `auto-safe` can succeed only when allowlisted and enabled
- `auto-safe` otherwise degrades durably
- `/new` creates fresh sessions by default
- already-healthy services become `action_stub_not_actionable`
- `/why-not-auto` and `/tail` explain current state clearly

### Console and assistant boundaries

- `tests/integration/test_runtime_console_api.py`
- `tests/unit/test_runtime_console_server.py`
- `tests/unit/test_runtime_assistant_api.py`

Proves:

- console approval/deny paths reflect runtime truth
- console can export handoff and show verification state
- UI remains panel-first and assistant stays secondary
- assistant is grounded, session-scoped, non-persistent, and fails closed on generic planner asks

### Artifact reconstruction and handoff

- `tests/integration/test_session_artifact_context.py`
- `tests/integration/test_handoff_context_assembly.py`
- `tests/integration/test_handoff_regeneration_flow.py`

Proves:

- `SessionArtifactContext` rebuilds latest verified artifacts
- missing verifier/tool artifacts surface as synthetic failures
- handoff assembly respects precedence
- regeneration fails honestly when required artifacts are missing

### Working memory boundaries

- `tests/integration/test_incident_working_memory_flow.py`

Proves:

- first working memory snapshot is written at hypothesis
- recommendation updates it
- failed recommendation does not overwrite it
- successful outcome verification clears the validation gap and rewrites memory with resolved state

### Core invariants

- `tests/unit/test_permission_policy.py`
- `tests/unit/test_action_approval_gate_contract.py`
- `tests/unit/test_runtime_execution.py`
- `tests/unit/test_resumable_slice_harness.py`

Proves:

- risk-based permission policy
- approval gate contract consistency
- synthetic failure normalization
- shared harness event ordering and checkpoint behavior

## 14. Current Limitations

- Only one live incident family is implemented: `deployment-regression`.
- Only one write path exists: rollback to the previous known-good version.
- The live target is a local demo HTTP service, not a real operational integration.
- Replay/eval coverage is intentionally narrow: supported branch and conservative branch.
- The assistant pane is a bounded deterministic explainer, not an open-ended model-driven copilot.
- The generic loop protocols exist, but there is no broad generic loop runtime yet.
- Project memory and cross-incident promotion are intentionally deferred.
- The console is deliberately minimal and local.
- The repo is stronger as a runtime-engineering milestone than as a finished product.

These are not accidental omissions. They are scope boundaries.

## 15. Interview Framing

### Good 30-second explanation

"This repo is a verifier-driven, durable, approval-gated incident-response runtime in Python.
It moves a narrow incident chain from triage to an approval boundary, and for one live
deployment-regression slice it can execute a bounded rollback and then verify recovery from
external runtime state. The main value is not broad autonomy. It is explicit runtime truth:
checkpoints, append-only transcripts, artifact reconstruction, approval provenance, and durable
handoff."

### What interviewers should hear clearly

- the project is narrow on purpose
- verification decides progression
- durable artifacts define truth
- approval is explicit and auditable
- conservative behavior is implemented, not just described
- the repo stops honestly before claiming broad automation

### Strongest technical differentiators

- `SessionArtifactContext`
- synthetic failure normalization
- separation of checkpoint, transcript, working memory, and handoff
- post-approval bounded write semantics
- replay/eval plus live-path consistency

### Weakest areas to admit honestly

- breadth
- real integrations
- product polish
- general autonomy

## 16. Recommended Study Path

1. Read `README.md`, `AGENTS.md`, `docs/architecture.md`, and `docs/product/PRODUCT_BRIEF.md`.
   This gives you the repo's truth boundaries.
2. Read `docs/usage.md`, `docs/demo.md`, and `docs/operator_shell_smoke_checklist.md`.
   This gives you the operator-facing flows.
3. Open `docs/examples/deployment_regression_payload.json` and `src/runtime/demo_target.py`.
   This makes the live slice concrete.
4. Read the step chain in order:
   `incident_triage.py`, `incident_follow_up.py`, `incident_evidence.py`,
   `incident_hypothesis.py`, `incident_recommendation.py`, `incident_action_stub.py`.
5. Read the live post-approval path:
   `deployment_rollback_execution.py` and `deployment_outcome_verification.py`.
6. Read each tool beside its verifier. This is where verifier-driven progression becomes obvious.
7. Read `src/runtime/execution.py`, `src/runtime/harness.py`, and
   `src/context/session_artifacts.py`.
   This is the runtime spine.
8. Read `src/memory/checkpoints.py`, `src/transcripts/models.py`,
   `src/memory/incident_working_memory.py`, and `src/context/handoff*.py`.
   This is the durable state model.
9. Read `src/runtime/shell.py`, `src/runtime/console_api.py`, `src/runtime/assistant_api.py`,
   and `src/runtime/inspect.py`.
   This is the operator surface layer.
10. Run the two eval scenarios and one live demo session. Then inspect the generated checkpoint,
    transcript, working memory, and handoff artifacts directly.
11. Read the integration tests listed in Section 13. They are the best executable truth source.
12. Only after that read the longer interview docs. At that point they will feel obvious instead
    of abstract.

## 17. Bottom Line

This repository is best understood as a completed narrow runtime milestone:

- verifier-driven
- durable
- approval-gated
- audit-friendly
- resumable
- honest about its scope

It is not trying to prove that a model can do everything. It is trying to prove that the things it
does are structurally defensible.

# Verifier-Driven Incident Response Agent Harness

This repository is a verifier-driven, durable, approval-gated incident-response runtime and the
current product prototype for `On-Call Copilot`. Today it supports one honest, demo-grade live
path for the `deployment-regression` incident family on a local demo target, plus replay/eval
coverage, a minimal panel-first Operator Console, and a terminal Operator Shell over the same
runtime truth. It is not a coding agent, not a mature ops product, and not a broad autonomous
remediation system.

## Start Here

- [Product Brief](docs/product/PRODUCT_BRIEF.md): controlling product spec for `On-Call Copilot`
- [Positioning](docs/product/POSITIONING.md): concise framing for what this repo is, and what it
  is not
- [Product One-Pager](docs/product/ONE_PAGER.md): recruiter-readable overview of the current
  product slice
- [Personas](docs/product/PERSONAS.md): who the current operator product is for
- [User Journeys](docs/product/USER_JOURNEYS.md): panel-first operator workflows grounded in repo
  truth
- [Product Metrics](docs/product/METRICS.md): demo-stage measures for safe incident decision
  compression
- [Phase 1 Operator Console PRD](docs/product/PHASE1_OPERATOR_CONSOLE_PRD.md): current console
  scope and constraints
- [Phase 1 API Mapping](docs/phase1_api_mapping.md): how console surfaces map to checkpoints,
  transcripts, and `SessionArtifactContext`
- [Phase 1.5 Assistant Mapping](docs/phase15_assistant_mapping.md): how the session-scoped
  assistant stays secondary and grounded
- [Architecture Summary](docs/architecture.md): runtime seams, durable-state layers, and safety
  boundaries
- [Usage Guide](docs/usage.md): practical command reference for the console, shell, and direct CLI
- [Demo Guide](docs/demo.md): fastest walkthrough of the current live deployment-regression path

## Product Snapshot

- `On-Call Copilot` is a narrow operator-facing product prototype over the same verifier-driven,
  durable, approval-gated runtime described below.
- It is for the on-call engineer, the approver reviewing the bounded rollback candidate, and the
  next-shift operator resuming the session.
- Its core value is safe incident decision compression: make the current session, approval
  boundary, verifier state, and handoff continuity easier to understand from one surface.
- It is not a coding agent. The center of gravity is incident state, approval, verification, and
  handoff continuity, not source editing or generic coding workflows.
- Today the scope is intentionally narrow: one `deployment-regression` live path, one bounded
  rollback action, one local demo target, and one thin product layer over the same runtime truth.

## What the Product Looks Like

`On-Call Copilot` is panel-first, not chat-first. The visible product surface today is a minimal
local Operator Console over existing durable runtime state:

- `Sessions list`: recent sessions with current phase, requested and effective mode, approval
  state, latest verifier summary, and last updated time
- `Incident detail / timeline / actions`: current phase, next recommended action, evidence
  summary, verification summary, recent checkpoint and verifier activity, and bounded approval,
  deny, verify, and handoff actions
- `Session-scoped assistant pane`: a secondary explainer surface for the selected session

The assistant is intentionally secondary. It explains the selected session from checkpoint,
transcript, verifier, and handoff truth, but it does not own incident state, approval state,
recovery state, or durable chat history.

Console screenshot/GIF to be added.

## 60-Second Demo Flow

1. Open `oncall-agent console`.
2. Select the current `deployment-regression` session from the sessions list.
3. Inspect whether the session is blocked, ready for approval, denied, or already verifier-backed
   as recovered from the main incident view.
4. Ask the session-scoped assistant, `Why is this session blocked?`, to get a bounded explanation
   grounded in current runtime truth.
5. Approve the bounded rollback candidate when the session is waiting at the approval boundary.
6. Rerun verification and confirm whether recovery is verified from external runtime state.
7. Export handoff so the next operator can resume from durable session truth instead of ad hoc
   notes.

## What This Project Can Do Today

The implemented runtime chain is explicit:

`triage -> follow-up -> evidence -> hypothesis -> recommendation -> approval-gated action stub`

For live approved `deployment-regression` sessions, the chain continues through:

`bounded rollback execution -> outcome verification`

What that means in practice:

- start an incident from a structured payload
- gather deterministic evidence from a local demo target
- produce a verifier-backed deployment-regression hypothesis and recommendation
- surface one approval-gated rollback candidate
- execute one bounded rollback after approval
- verify recovery against external `/deployment`, `/health`, and `/metrics` endpoints
- export inspectable audit and handoff artifacts from durable session state
- run replay/eval scenarios for a supported branch and a conservative non-actionable branch

## What This Project Intentionally Does Not Do

- broad remediation across arbitrary systems
- generic planner, generic chatbot, or coding-agent workflows
- broad autonomous remediation beyond the existing bounded rollback path
- generic multi-incident orchestration or arbitrary action libraries
- mature production integrations, routing, policy authoring, or enterprise workflow claims
- multi-agent complexity

The repository is intentionally narrow. It should be read as a durable runtime milestone with one
real operator-facing product slice, not as a finished ops platform.

This repository currently proves one narrow live closed loop:

- one incident family: `deployment-regression`
- one bounded mitigation: rollback to the known-good version
- one local demo target
- one thin console and shell over the same runtime

The replay/eval path remains important because it shows the verifier-backed chain and conservative
behavior without execution. The live path only continues beyond the approval boundary for the
existing bounded rollback slice.

## Quickstart

Install the repository in editable mode:

```bash
python -m pip install -e '.[dev]'
```

If the `oncall-agent` console script is not available in your shell, use:

```bash
.venv/bin/python -m runtime.cli <command> ...
```

Run one replay scenario:

```bash
oncall-agent run-eval incident-chain-replay-recent-deployment \
  --output-root /tmp/oncall-agent-demo
```

Expected highlights:

- `path_classification: supported`
- `final_stage: action_stub`
- `handoff_status: written`

Launch the panel-first Operator Console:

```bash
oncall-agent console
```

Launch the terminal Operator Shell:

```bash
oncall-agent shell
```

## Operator Surface

The repository has three operator-facing surfaces over the same runtime truth. They read and act on
the same reconciled checkpoints, append-only transcripts, `SessionArtifactContext`, verifier
artifacts, and handoff artifacts; they do not own alternate session state.

- `Operator Console`: a minimal local browser surface over checkpoints, transcripts,
  `SessionArtifactContext`, verification artifacts, and handoff artifacts. It shows recent
  sessions, incident detail, recent timeline activity, bounded approval and deny controls,
  verification state, handoff access, and a session-scoped assistant pane.
- `Operator Shell`: a terminal-first operator surface over the same checkpoints, transcripts,
  working memory, inspection, and handoff seams. It does not introduce a second state layer.
- `Direct CLI`: direct commands remain available for `start-incident`, `resolve-approval`,
  `verify-outcome`, `run-eval`, `inspect-session`, `inspect-artifacts`, `show-audit`, and
  `export-handoff`.

Core shell commands:

- `/sessions`
- `/new <payload-path>`
- `/resume <session-id|index>`
- `/mode manual|semi-auto|auto-safe`
- `/status`
- `/why-not-auto`
- `/tail`
- `/approve <reason>`
- `/deny <reason>`
- `/verify`
- `/handoff`

Autonomy modes:

- `manual`: inspection-first; no shell-driven write execution
- `semi-auto`: drive the read-only chain to the approval boundary, then stop
- `auto-safe`: only auto-execute the bounded deployment-regression rollback when the repo-local
  policy explicitly enables it, the target base URL is allowlisted, the verified rollback
  candidate exists, the live version checks still match, and no blocking gaps remain; otherwise
  degrade to `semi-auto` with a durable reason

The default policy in `.oncall/settings.toml` fails closed. `auto-safe` is disabled until it is
explicitly enabled.

## Live Deployment-Regression Demo

Start the local demo target in one terminal:

```bash
oncall-agent run-demo-target --port 8001
```

Use the shell as the main end-to-end operator flow:

```text
/sessions
/mode semi-auto
/new docs/examples/deployment_regression_payload.json
/status
/why-not-auto
/approve Rollback approved for the live demo target.
/verify
/handoff
/exit
```

Or use the direct CLI surfaces:

```bash
oncall-agent start-incident \
  --family deployment-regression \
  --payload docs/examples/deployment_regression_payload.json \
  --json

oncall-agent resolve-approval <session_id> --decision approve --json
```

If you want the panel-first view while the live session exists, open:

```bash
oncall-agent console
```

Expected live-path highlights:

- initial phase reaches `action_stub_pending_approval`
- approval records a bounded rollback decision
- final phase becomes `outcome_verification_succeeded`
- recovery is verified from external runtime state

For a step-by-step walkthrough, use [Demo Guide](docs/demo.md). For a human-guided local rerun of
the shell flows, use [Operator Shell Smoke Checklist](docs/operator_shell_smoke_checklist.md).

## Why This Runtime Is Technically Credible

- verifier-driven progression with explicit contract-stage then outcome-stage verifier flow
- append-only JSONL transcripts instead of hidden in-memory state
- resumable checkpoints for control state, committed only when reconciled with the matching
  `checkpoint_written` transcript marker
- explicit uncommitted transcript tail after the committed checkpoint boundary, with trusted
  artifact reconstruction from the committed prefix only
- transcript-backed verifier interruption via `verifier_request`; `pending_verifier` remains
  committed post-verifier control state only
- bounded `IncidentPhase` for true phase-bearing contract fields, with fail-closed invalid-phase
  handling and explicit valid-but-incompatible runtime handling where intentionally preserved
- wrong-step runtime entry fails closed before new transcript or checkpoint writes
- `SessionArtifactContext` as the durable recovery and audit seam
- explicit approval boundaries and approval provenance for risky actions
- external outcome verification after the one implemented rollback action
- `IncidentWorkingMemory` and stable handoff artifacts for continuity without replacing runtime
  truth
- operator console, shell, and direct CLI as thin surfaces over the same runtime truth
- replay/eval coverage that exercises the real chain and preserves inspectable artifacts

Current durable state seams:

- checkpoints in `sessions/checkpoints/<session_id>.json`
- append-only transcripts in `sessions/transcripts/<session_id>.jsonl`
- incident working memory in `sessions/working_memory/<incident_id>.json`
- derived handoff artifacts in `sessions/handoffs/<incident_id>.json`

## Deeper Docs

- [Product Brief](docs/product/PRODUCT_BRIEF.md)
- [Positioning](docs/product/POSITIONING.md)
- [Product One-Pager](docs/product/ONE_PAGER.md)
- [Personas](docs/product/PERSONAS.md)
- [User Journeys](docs/product/USER_JOURNEYS.md)
- [Product Metrics](docs/product/METRICS.md)
- [Phase 1 Operator Console PRD](docs/product/PHASE1_OPERATOR_CONSOLE_PRD.md)
- [Phase 1 API Mapping](docs/phase1_api_mapping.md)
- [Phase 1.5 Assistant Mapping](docs/phase15_assistant_mapping.md)
- [Architecture Summary](docs/architecture.md)
- [Usage Guide](docs/usage.md)
- [Demo Guide](docs/demo.md)
- [Project Summary](docs/project_summary.md)
- [Resume Framing](docs/resume.md)
- [Interview Guide](docs/interview.md)

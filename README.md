# Verifier-Driven Incident Response Agent Harness

This repository is a verifier-driven, durable, approval-gated incident-response runtime.
Today it supports one honest, demo-grade live ops path for the `deployment-regression` incident
family on a local demo target, plus a thin operator shell with `manual`, `semi-auto`, and
fail-closed `auto-safe` modes.

It is not a mature ops product, not a coding agent, and not a broad autonomous remediation
system. The point of the repository is to show a reliable harness spine for incident handling:
typed slices, append-only transcripts, resumable checkpoints, explicit approval boundaries,
external outcome verification, and durable recovery through `SessionArtifactContext`.

The repository also includes a narrow operator-facing product slice for `On-Call Copilot`: a
panel-first incident decision and verification surface over that same runtime.

## Start Here

- [Usage Guide](docs/usage.md): practical command reference for the shell and direct CLI surfaces
- [Demo Guide](docs/demo.md): 5-minute walkthrough of the current live deployment-regression path
- [Architecture Summary](docs/architecture.md): runtime seams, durable-state layers, and safety
  boundaries
- [Product Brief](docs/product/PRODUCT_BRIEF.md): controlling product spec for `On-Call Copilot`
- [Product One-Pager](docs/product/ONE_PAGER.md): recruiter-readable overview of the current
  product slice
- [Personas](docs/product/PERSONAS.md) and [User Journeys](docs/product/USER_JOURNEYS.md):
  operator-facing product framing for the current workflow
- [Product Metrics](docs/product/METRICS.md): proto-product success measures for the current slice
- [Operator Shell Smoke Checklist](docs/operator_shell_smoke_checklist.md): human-guided local
  rerun of the current shell flows
- [Project Summary](docs/project_summary.md): short repository framing

## What This Project Can Do Today

The implemented runtime chain is explicit:

`triage -> follow-up -> evidence -> hypothesis -> recommendation -> approval-gated action stub`

For the live `deployment-regression` family, the approved branch continues through:

`bounded rollback execution -> outcome verification`

What that means in practice:

- start an incident from a structured payload
- gather deterministic evidence from a local demo target
- produce a verifier-backed deployment-regression hypothesis
- surface one approval-gated rollback candidate
- execute one bounded rollback after approval
- verify recovery against external `/deployment`, `/health`, and `/metrics` endpoints
- export inspectable handoff and audit artifacts from durable session state

## What This Project Intentionally Does Not Do

- broad remediation across arbitrary systems
- generic planner or open-ended autonomous loop behavior
- multi-agent orchestration
- production deployment integrations or approval UI
- broad autonomy beyond the existing bounded rollback path

The repository is intentionally narrow. It should be read as a durable runtime milestone with one
real operator-facing product slice, not as a finished ops platform.

## Quickstart

Install the repository in editable mode:

```bash
python -m pip install -e '.[dev]'
```

If the console script is not available in your shell, use:

```bash
.venv/bin/python -m runtime.cli <command> ...
```

Run one replay scenario:

```bash
oncall-agent run-eval incident-chain-replay-recent-deployment --output-root /tmp/oncall-agent-demo
```

Expected highlights:

- `path_classification: supported`
- `final_stage: action_stub`
- `handoff_status: written`

Launch the operator shell:

```bash
oncall-agent shell
```

Launch the minimal browser-based Operator Console:

```bash
oncall-agent console
```

It serves a panel-first local console over the same runtime truth and adds a session-scoped
assistant pane that explains the selected session without becoming workflow authority.

## Operator Console

The Operator Console is a minimal local browser surface over the existing checkpoints, transcripts,
`SessionArtifactContext`, verification artifacts, and handoff artifacts.

It exposes:

- recent sessions
- session detail
- recent timeline activity
- approval / deny controls
- verification and handoff access
- a secondary session-scoped assistant pane

The assistant pane is intentionally narrow. It explains and summarizes the selected session, but
it does not persist chat history, own incident state, own approval state, or bypass the existing
approval and verification seams.

## Operator Shell

The shell remains the terminal-first operator surface over the existing runtime. It does not
introduce a second state layer; it uses the same checkpoints, transcripts, working memory,
inspection, and handoff seams as the direct CLI.

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
- `auto-safe`: only auto-execute the existing bounded deployment-regression rollback when the
  repo-local policy is enabled, the base URL is allowlisted, the verified rollback candidate
  exists, the live version checks still match, and no blocking gaps remain; otherwise degrade to
  `semi-auto` with a durable reason

The default policy in `.oncall/settings.toml` fails closed. `auto-safe` is disabled until it is
explicitly enabled.

## Live Deployment-Regression Demo

Start the local demo target in one terminal:

```bash
oncall-agent run-demo-target --port 8001
```

Use the shell as the main operator flow:

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

Expected live-path highlights:

- initial phase reaches `action_stub_pending_approval`
- approval records a bounded rollback decision
- final phase becomes `outcome_verification_succeeded`
- recovery is verified from external runtime state

For a step-by-step walkthrough, use [Demo Guide](docs/demo.md). For a human-guided local shell
rerun, use [Operator Shell Smoke Checklist](docs/operator_shell_smoke_checklist.md).

## Why This Runtime Is Technically Credible

- verifier-driven progression instead of treating model output as completion
- append-only JSONL transcripts instead of hidden in-memory state
- resumable checkpoints for control state
- `SessionArtifactContext` as the durable recovery and audit seam
- explicit approval boundaries for risky actions
- external outcome verification after the one implemented rollback action

Current durable state seams:

- checkpoints in `sessions/checkpoints/<session_id>.json`
- append-only transcripts in `sessions/transcripts/<session_id>.jsonl`
- incident working memory in `sessions/working_memory/<incident_id>.json`
- derived handoff artifacts in `sessions/handoffs/<incident_id>.json`

## Limitations And Honest Scope

This repository currently proves one narrow live closed loop:

- one incident family: `deployment-regression`
- one bounded mitigation: rollback to the known-good version
- one local demo target
- one thin operator shell over the same runtime

The replay/eval path remains important because it shows the verifier-backed chain and conservative
behavior without execution. The live path only continues beyond the approval boundary for the
existing bounded rollback slice.

## Deeper Docs

- [Product Brief](docs/product/PRODUCT_BRIEF.md)
- [Product One-Pager](docs/product/ONE_PAGER.md)
- [Personas](docs/product/PERSONAS.md)
- [User Journeys](docs/product/USER_JOURNEYS.md)
- [Product Metrics](docs/product/METRICS.md)
- [Positioning](docs/product/POSITIONING.md)
- [Usage Guide](docs/usage.md)
- [Demo Guide](docs/demo.md)
- [Architecture Summary](docs/architecture.md)
- [Project Summary](docs/project_summary.md)
- [Resume Framing](docs/resume.md)
- [Interview Guide](docs/interview.md)

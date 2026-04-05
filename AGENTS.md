# AGENTS.md

## Project Overview

This repository builds a **verifier-driven incident response agent** inspired by harness engineering patterns from modern coding agents.

The operator-facing product direction for this repository is **On-Call Copilot**.
Treat `docs/product/PRODUCT_BRIEF.md` as the controlling product spec for product-facing work.

The goal is **not** to clone Claude Code or build a generic chatbot.
The goal is to build a **production-oriented agent harness** for on-call / operations / troubleshooting workflows, with strong emphasis on:

- controlled tool execution
- permission-gated actions
- skill-based workflows
- automated verification
- resumable long-running sessions
- evaluation and replay
- auditability and safety

This project should be suitable for:
- resume / internship applications for agent engineering roles
- system design and backend interviews
- demonstrating agent reliability engineering, not just prompt orchestration

This repository uses **Python as the main implementation language**.
We borrow harness ideas from TypeScript-first systems, but the implementation should feel native to Python.

---

## Product Definition

Product-facing work should be read through the `On-Call Copilot` lens:

- an operator-facing incident decision and verification product
- grounded in the existing verifier-driven runtime
- intentionally narrow in scope
- distinct from a coding copilot or generic agent platform

The agent should help with incident handling workflows such as:

- triaging alerts
- reading logs / metrics / runbooks
- proposing action plans
- executing allowed read-only or approved write actions
- verifying whether remediation actually worked
- producing shift handoff / postmortem-ready summaries

The agent is **verifier-driven**:
execution is not considered complete just because the model says so.
A task is only considered complete when corresponding verifiers confirm success.

## Specification Precedence

When documents or ideas pull in different directions, use this precedence order:

1. implemented runtime truth plus durable artifacts
2. `docs/architecture.md`
3. `docs/product/PRODUCT_BRIEF.md`
4. the relevant phase PRD under `docs/product/`
5. `README.md`

Interpretation rules:

- runtime truth and architecture constraints override product wishfulness
- `PRODUCT_BRIEF.md` controls product direction and scope
- phase PRDs refine the product brief for a slice; they do not override runtime constraints
- `README.md` is a landing-page summary, not the authority for broader scope or behavior changes

---

## Core Principles

### 1. Harness-first
We prioritize the agent runtime / harness over flashy UI.
The most important parts of this project are:
- loop design
- tool contracts
- permission model
- skill loading
- verification flow
- memory / resumability
- eval harness

### 2. Reliability over breadth
Prefer a narrow, deep, reliable system over a broad, vague one.
Do not add features unless they improve:
- safety
- observability
- verification
- resumability
- evaluability

### 3. Minimal but real
Prefer simple architecture with strong boundaries.
Avoid over-engineering and unnecessary frameworks.

### 4. Verification is mandatory
Every meaningful action path must have a verification story.
No "done" without validation.

### 5. Human approval for risk
High-risk or write actions must be permission-gated.
Unsafe autonomy is a bug.

### 6. Small patches, explicit reasoning
All code changes should be incremental, reviewable, and justified against harness goals.

### 7. Pythonic implementation, strict contracts
Use Python ergonomics, but keep contracts explicit and structured.
Favor typed models, validation, and clear interfaces over loose dynamic behavior.

---

## Non-Goals

The following are explicitly out of scope unless later approved:

- turning the repo into a generic planner
- building a generic personal assistant
- building a travel planner
- building a fully autonomous DevOps platform
- building a broad autonomous remediation agent
- adding multi-agent complexity without clear benefit
- adding heavy framework dependencies just to look advanced
- optimizing for demo visuals over engineering quality

---

## Primary Architecture Targets

The system should evolve toward the following components:

1. **Agent Loop**
   - iterative query / think / tool / observe cycle
   - supports multi-step execution
   - supports interruption and resume
   - records structured transcripts

2. **Tool Registry**
   - strongly typed tool schemas
   - clear separation between read-only, write, dangerous tools
   - consistent tool result format
   - synthetic error result support

3. **Permission Engine**
   - classify tools/actions as `allow`, `ask`, or `deny`
   - default-safe behavior
   - approval flow for risky actions
   - audit log of decisions

4. **Skill System**
   - reusable workflow units
   - skills stored as explicit project assets
   - each skill defines purpose, trigger conditions, inputs, outputs, and verifier expectations

5. **Verifier System**
   - API verifier
   - CLI/system verifier
   - optional web/UI verifier
   - verifiers are first-class components, not ad hoc scripts

6. **Session / Memory System**
   - persistent execution state
   - resumable sessions
   - incident timeline
   - handoff summary generation
   - project memory for stable operational knowledge

7. **Eval Harness**
   - scenario-based evaluation
   - deterministic or semi-deterministic replay where possible
   - metrics for task success, unsafe action rate, verification pass rate, and recovery behavior

---

## Python Technology Direction

Unless there is a strong reason otherwise, prefer the following stack:

- **Python 3.11+**
- **Pydantic v2** for validated data models and tool/result schemas
- **typing / Protocol / ABC / TypedDict / dataclass** for interface boundaries
- **asyncio** for orchestration where concurrency is useful
- **httpx** for API calls
- **pytest** for tests
- **ruff** for linting and formatting
- **mypy** or **pyright** for static type checking
- **Playwright for Python** for web verifiers if UI verification is needed

Do not introduce large frameworks unless they solve a real harness problem.

---

## Suggested Repository Structure

Keep the structure simple and stable.

```text
.
├── AGENTS.md
├── README.md
├── pyproject.toml
├── docs/
│   ├── architecture.md
│   ├── decisions/
│   └── prompts/
├── skills/
│   ├── incident-triage/
│   │   └── SKILL.md
│   ├── runbook-matcher/
│   │   └── SKILL.md
│   ├── api-health-check/
│   │   └── SKILL.md
│   └── handoff-writer/
│       └── SKILL.md
├── verifiers/
│   ├── api/
│   ├── cli/
│   └── web/
├── evals/
│   ├── scenarios/
│   ├── fixtures/
│   ├── runners/
│   └── reports/
├── sessions/
│   └── schema/
├── src/
│   ├── agent/
│   │   ├── loop.py
│   │   ├── runner.py
│   │   └── state.py
│   ├── tools/
│   │   ├── base.py
│   │   ├── registry.py
│   │   ├── models.py
│   │   └── implementations/
│   ├── permissions/
│   │   ├── policy.py
│   │   ├── classifier.py
│   │   └── models.py
│   ├── skills/
│   │   ├── loader.py
│   │   ├── registry.py
│   │   └── models.py
│   ├── verifiers/
│   │   ├── base.py
│   │   ├── registry.py
│   │   └── implementations/
│   ├── memory/
│   │   ├── checkpoints.py
│   │   ├── project_memory.py
│   │   └── session_memory.py
│   ├── evals/
│   │   ├── runner.py
│   │   ├── scoring.py
│   │   └── models.py
│   ├── transcripts/
│   │   ├── writer.py
│   │   └── models.py
│   ├── llm/
│   │   ├── client.py
│   │   └── models.py
│   └── utils/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── regression/
└── scripts/
```

---

## Coding Rules

### General

* Prefer explicit types.
* Prefer small composable modules.
* Avoid hidden side effects.
* Avoid unnecessary abstractions.
* Keep control flow easy to inspect.

### Python Style

* Use `Pydantic` models for external boundaries and structured events.
* Use `dataclass` only where validation is not needed.
* Use `Protocol` or `ABC` for stable interfaces.
* Prefer `Enum` for policy states and verifier outcomes.
* Keep async boundaries explicit.
* Avoid overly magical decorators or dynamic runtime patching.

### Tooling

Every tool must have:

* input schema
* output schema
* risk classification
* runtime contract
* structured failure mode
* predictable logging behavior

### Permissions

* Read-only tools should be easiest to use.
* Write actions must go through policy checks.
* Dangerous actions must be denied by default unless explicitly allowed.

### Errors

* Never silently swallow tool errors.
* All tool failures must become structured observations.
* The loop must remain internally consistent even on partial failure.

### Logging / Observability

Log session steps in structured form.
Record:

* model step
* tool call
* tool result
* permission decision
* verifier result
* resume checkpoint

Prefer machine-readable event records over free-form logs.

---

## Skills Contract

Each skill must define:

* name
* purpose
* when to use
* required inputs
* optional inputs
* expected outputs
* verifier expectations
* safety / permission considerations
* examples

Each skill should be reusable and composable.
Do not bury critical behavior only inside prompts.

Example skill candidates:

* `incident-triage`
* `log-summarizer`
* `runbook-matcher`
* `api-health-check`
* `rollback-checker`
* `handoff-writer`

Python code should treat skills as explicit assets with typed metadata and a stable loading path.

---

## Verifier Contract

Verifiers are first-class.

Every verifier should define:

* target condition
* input contract
* execution method
* pass/fail criteria
* failure diagnostics
* retry policy if applicable

Examples:

* API returns healthy status
* error rate falls below threshold
* service process is running
* critical page loads successfully
* alert no longer firing

If an action cannot be verified, the system should explicitly report that it is unverified.

Verifier outputs should be structured and typed, not plain strings only.

---

## Transcript and Session Rules

The system should record structured transcripts for every meaningful step.

Each transcript event should include, where applicable:

* session id
* timestamp
* event type
* model reasoning summary or step note
* tool request
* tool result
* verifier result
* permission decision
* checkpoint marker

Prefer append-only structured records such as `.jsonl` or equivalent durable storage.

Session recovery should not depend only on raw chat history.
Important execution state must be reconstructable from structured state plus transcript events.

---

## Eval Philosophy

This repo must include scenario-based evals early.

Target scenario families:

* service returns elevated 5xx
* dependency timeout causes partial outage
* bad config requires rollback
* CPU / memory spike incident
* web UI broken but backend healthy
* false positive alert / no-op case

Key metrics:

* task success rate
* verifier pass rate
* unsafe action rate
* unnecessary tool call rate
* recovery after interruption
* mean steps to resolution
* handoff quality

Do not wait until the end of the project to define evals.

Prefer Python-native eval runners that are deterministic where possible and reproducible in CI.

---

## Testing Rules

Every non-trivial change should consider tests.

Preferred test layers:

* **unit tests** for schemas, registry logic, policy decisions, parser behavior
* **integration tests** for loop + tools + verifier interactions
* **regression tests** for known incident scenarios or failure modes

At minimum, new behavior should include:

* positive case
* failure case
* edge case if the code touches control flow or policy logic

Do not merge behavior that only works in the happy path.

---

## Development Workflow

For non-trivial tasks, always follow:

1. understand current architecture
2. write or update a short plan
3. identify affected modules
4. implement minimum viable patch
5. add or update tests
6. add or update verifier path if needed
7. update docs if behavior changed
8. summarize what changed and why

Do not skip verification.
Do not make broad unrelated refactors.

---

## Definition of Done

A task is only done when all applicable items are true:

* implementation works
* tests pass
* verifier path exists or is explicitly documented as unavailable
* no harness invariants are broken
* docs stay consistent
* change is small enough to review
* rationale is documented in the task summary

---

## What Codex Should Optimize For

When helping on this repository, optimize for:

1. correctness
2. safety
3. verifiability
4. clarity of architecture
5. small reviewable diffs
6. maintainability
7. resume/interview value

Do **not** optimize for:

* cosmetic complexity
* unnecessary agent fan-out
* fancy but weak abstractions
* demo-only features without engineering depth

---

## What to Do Before Writing Code

Before changing code, Codex should:

* read `README.md`
* read this file
* read `docs/architecture.md`
* read `docs/product/PRODUCT_BRIEF.md`
* read the relevant phase PRD in `docs/product/` when the task is product-slice-specific
* inspect repository layout
* inspect relevant module interfaces
* identify existing invariants
* propose a brief plan for non-trivial work

If the task is large, split it into phases instead of attempting a giant patch.

For product-facing work, `docs/product/PRODUCT_BRIEF.md` is the controlling spec. Do not add
features or framing that conflict with it unless the brief itself is intentionally updated.

---

## Subagent Policy

Subagents are optional and must be used selectively.

Use subagents only when:

* the task is clearly separable
* context isolation is beneficial
* output can be reviewed independently
* the work is evaluative, documentary, or verifier-oriented

Good subagent candidates:

* verifier authoring
* eval scenario authoring
* documentation consistency audit
* code review / harness invariant audit

Avoid subagents for:

* early core architecture design
* tightly coupled refactors
* naming or boundary decisions still in flux
* tasks where multiple agents will likely diverge

Main implementation should usually remain in the primary thread.

---

## Preferred Early Milestones

### Milestone 1

* repo scaffold
* architecture docs
* typed tool registry
* permission model skeleton
* minimal agent loop

### Milestone 2

* skill loader
* structured session transcript
* basic memory / resume checkpoint
* first read-only tools

### Milestone 3

* verifier interfaces
* API/CLI verifier implementations
* first scenario evals

### Milestone 4

* approval flow for write actions
* richer incident workflows
* handoff generator
* replay / audit improvements

### Milestone 5

* polish for resume/demo
* benchmark/eval report
* architecture cleanup
* final documentation

---

## Anti-Patterns

Avoid these common mistakes:

* giant rewrites without a plan
* adding frameworks before stabilizing contracts
* mixing verifier logic into random business logic
* letting prompts replace software structure
* declaring success without evidence
* adding multi-agent complexity too early
* storing important state only in free-form text
* relying on untyped dicts at major system boundaries
* hiding core logic inside notebooks or scripts

---

## Final Reminder

This is an agent engineering project.
The core deliverable is a reliable, explainable, verifier-driven harness for incident response workflows.

Future product work should strengthen the repository as an operator-facing `On-Call Copilot`, not
turn it into a generic planner, generic coding copilot, or broad autonomous remediation agent.
Preserve approval gating, runtime truth in checkpoints and transcripts, `SessionArtifactContext`,
and the existing narrow architecture boundaries.

Every important design choice should make the project:

* safer
* easier to verify
* easier to resume
* easier to evaluate
* easier to explain in an interview

Use Python naturally, but keep the engineering discipline high.
The implementation language is Python; the standard of rigor should still feel like a well-designed harness system.

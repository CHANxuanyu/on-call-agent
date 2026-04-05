# Claude Code Comparison

This repository borrows a few durable harness ideas from broader agent systems such as Claude
Code, but it applies them to a narrower problem: verifier-driven incident-response execution with
strong replay, resume, and approval boundaries.

The comparison matters only insofar as it clarifies what this repository intentionally adapted and
what it intentionally left out for the current milestone.

## What This Repo Already Adapted Successfully

- durable checkpoint and transcript separation instead of relying on chat history alone
- shared artifact reconstruction through `SessionArtifactContext`
- structured synthetic failure normalization for malformed, partial, or interrupted runtime paths
- explicit permission provenance rather than bare allow/deny booleans
- a thin shared resumable-slice harness to remove repeated resume/tool/verifier/checkpoint wiring
- a first semantic-memory slice through `IncidentWorkingMemory`

Those pieces are now implemented and covered by tests. They are part of the current runtime story,
not future plans.

## What This Repo Intentionally Does Not Copy

- a fully generic query loop
- multi-agent or coordinator orchestration
- hook-heavy lifecycle extension points
- classifier-driven auto-approval or bypass-permissions behavior
- context-compaction and transcript-surgery machinery
- broad product surface, UI, or coding-agent workflow features

Those omissions are deliberate. The repo is trying to show a narrow, credible incident harness
milestone rather than a broad agent product.

## Side-By-Side Positioning

| Area | This Repository | Broader Coding-Agent Systems |
| --- | --- | --- |
| Primary unit of progress | verifier-backed incident slice transitions | generic tool-augmented conversational turns |
| Resume source of truth | checkpoint plus append-only transcript events | broader turn/session state machinery |
| Safety boundary | explicit approval-aware action candidacy plus one bounded rollback demo path with external verification | broader execution workflows with richer product surfaces |
| Memory story | checkpoint control state, transcript execution truth, first incident-working-memory slice, handoff artifacts | larger memory and context-management systems |
| Scope choice | narrow deterministic incident chain | broad coding/product workflows |

## Why The Narrower Design Is Better Here

For interview and portfolio purposes, the narrower design is more defensible:

- each phase transition has a verifier story
- each durable artifact has a clear role
- failure paths stay replayable instead of disappearing into informal retry logic
- approval state is visible and auditable
- the runtime stops before claiming execution semantics it does not actually implement

That is a better fit for an incident-response harness milestone than importing broader coding-agent
complexity.

## Bottom Line

The useful ideas to adapt from broader agent runtimes were the invariants, not the breadth:
durable artifacts, resumability, structured failure handling, and explicit permission reasoning.
This repository now implements those ideas in incident-oriented form and intentionally stops short
of generic loop, multi-agent, or product-surface expansion.

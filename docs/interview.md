# Interview Guide

## 60-90 Second Introduction

I built a verifier-driven incident-response runtime in Python. The interesting part is not a model
calling tools by itself, but the runtime contracts around it: append-only structured transcripts,
checkpoint-driven resumability, explicit verifier-gated phase transitions, and approval-aware
state. I implemented the system in narrow slices from triage through follow-up, evidence,
hypothesis, recommendation, and an approval-gated action stub. I also added shared artifact
reconstruction through `SessionArtifactContext`, synthetic failure normalization, incident working
memory, and deterministic handoff artifact regeneration. The result is a small but reliable agent
harness that is auditable and replayable, without claiming real execution or broad autonomy.

## 2-3 Minute Version

The project started from a runtime question, not a product question. A lot of agent demos show a
model producing tool calls, but they often leave state, recovery, and auditability implicit. I
wanted to build something narrower and more defensible for incident-response workflows, where
operators care about what the system actually did, what evidence it used, and whether a risky
action is still blocked behind approval.

So I made the contracts explicit first. Skills are durable file assets. Execution history is
append-only JSONL. Resumable state lives in checkpoints. Each slice has a typed tool output and a
typed verifier result, and the session only advances when the verifier passes. On top of that I
added `SessionArtifactContext`, which loads checkpoint plus transcript once and reconstructs the
latest verified artifacts needed for resume. I also normalized malformed and partial runtime paths
into synthetic failures so the failure path is replayable instead of disappearing into ad hoc
branch logic.

The implemented chain is deliberately narrow: triage, follow-up target selection, evidence
reading, incident hypothesis, recommendation, and an approval-gated action stub. The runtime does
not execute real remediation. It stops when it can justify a structured action candidate and make
the approval boundary explicit. That was a deliberate milestone choice because it proves
resumability, verification, replayability, and safety boundaries before taking on real execution
semantics.

The later additions are also infrastructure-focused. I split out a first incident-working-memory
layer so semantic incident understanding does not get dumped into checkpoints. Then I built a
handoff context assembler and a stable handoff artifact writer plus regenerator, so operator-facing
handoff output can be reproduced deterministically from durable runtime state. That makes the
project useful to talk about both as runtime engineering and as incident-oriented systems design.

## Direct Answers

### What Is This Runtime For?

It is for incident-response workflows where the runtime has to be durable, resumable, and easy to
audit. It is designed to move a single incident through a narrow verifier-driven chain and produce
structured artifacts that support replay, evaluation, and operator handoff.

### How Does It Differ From A Coding Agent Like Claude Code?

Claude Code is a much broader product and focuses on software tasks in a coding environment. This
repo borrows mature harness ideas such as durable artifacts, resumability, and approval boundaries,
but applies them to incident-response state and operator safety. It does not try to reproduce a
coding-agent UI, general coding workflow, or broader product behavior.

### Why Use This Instead Of Claude Code For Incident-Response Workflows?

Because this repo is optimized for a different problem. It treats checkpoint state, transcript
history, verifier results, approval state, and handoff artifacts as first-class incident runtime
contracts. That makes it a better fit for explaining and testing incident-response harness design
than using a general coding agent and trying to layer incident semantics on top afterward.

## Likely Interview Questions

### Why make the system verifier-driven instead of trusting tool output?

Answer outline:
- Tool output alone does not prove the state transition is justified.
- Verifiers force each slice to check structure and branch correctness.
- That makes checkpoint phase changes auditable and harder to fake through optimistic control flow.

### Why did you keep the chain narrow instead of building a generic planner?

Answer outline:
- Narrow slices made the artifact contracts stable before introducing more autonomy.
- It reduced ambiguity in replay and failure handling.
- The result is more credible and easier to review than a broad framework with weak invariants.

### What is `SessionArtifactContext` solving?

Answer outline:
- Before it existed, steps repeatedly reconstructed prior verified artifacts themselves.
- It centralizes checkpoint plus transcript loading, artifact lookup, insufficiency handling, and
  synthetic failure interpretation.
- It improves maintainability without turning the runtime into a generic loop.

### What is the difference between checkpoint state, transcript history, and incident working memory?

Answer outline:
- checkpoint: control plane
- transcript: append-only execution truth
- incident working memory: compact semantic snapshot derived from verified state
- handoff artifacts are derived again from those layers and are not part of the control plane

### Why stop at an approval-gated action stub?

Answer outline:
- Producing a candidate and executing it are different safety problems.
- The milestone proves approval-aware action candidacy without pretending to solve safe execution.
- That was the right stopping point for a runtime-focused project.

### What makes the failure path strong here?

Answer outline:
- malformed or partial paths become typed synthetic failures
- missing required verifier/artifact chains are explicit
- replay and resume can distinguish insufficiency from failure instead of collapsing both into
  `None` or hidden exceptions

## Tradeoffs And Limitations

- The runtime is intentionally narrow and deterministic; it does not cover broad incident-response
  behavior.
- It does not execute remediation, integrate with real external systems, or include approval UI.
- Project memory is still deferred beyond the first incident-working-memory slice.
- The system is stronger as a harness milestone than as a finished operations product, which is
  exactly the intended tradeoff.

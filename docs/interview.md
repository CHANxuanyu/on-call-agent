# Interview Guide

## 60-90 Second Introduction

I built a verifier-driven incident-response agent harness in Python. The interesting part is not
the model behavior by itself, but the runtime contracts around it. The system uses file-based
skills, append-only structured transcripts, checkpoint-driven resumability, and explicit verifier
results to control phase transitions. I implemented the chain in narrow slices: triage, follow-up
target selection, evidence reading, hypothesis formation, recommendation, and finally an
approval-gated action stub. That last step is deliberate because I wanted to prove safe,
auditable action candidacy before any real execution. The repo also includes replay-style evals for
both a supported path and a conservative insufficient-evidence path, so the artifact flow is
testable end to end.

## 2-3 Minute Version

The project started from a harness question rather than a product question. A lot of agent demos
show a model calling tools, but they do not make the runtime durable, resumable, or easy to audit.
I wanted to build a small incident-response system that borrows mature harness patterns from tools
like Claude Code without cloning the product surface.

So I focused on a few core ideas. First, I made the contracts explicit: skills are file-based
assets, transcripts are append-only JSONL events, checkpoints capture resumable state, and
verifiers return structured pass/fail/unverified results. Second, I made each new behavior a
narrow slice instead of building a generic planner up front. The chain currently goes from triage
to follow-up target selection, then to evidence reading, then to a single structured hypothesis,
then to a single recommendation, and finally to an approval-gated action stub.

What matters is how each step resumes. A continuation step loads the latest checkpoint, reads the
transcript, reconstructs the exact prior artifact it depends on, and either proceeds with one
deterministic action or records an explicit conservative branch. It does not guess from free-form
history. And a step is not complete just because it produced output. It advances only when its
verifier confirms the output is structurally valid and justified by the prior artifact chain.

I intentionally stopped at the approval-gated action-stub stage. That preserves a meaningful safety
boundary: the harness can identify a plausible next action and record that approval is required,
but it does not mutate external systems. For me, that was the right engineering milestone because
it demonstrates reliability, auditability, and replayability before moving into real execution.

## Likely Interview Questions

### Why build this instead of a broader agent demo?

Answer outline:
- Broader demos often hide the runtime story behind prompts and UI
- I wanted to show engineering around state, verification, and safety
- Narrow scope made it possible to finish an end-to-end artifact chain credibly

### What does verifier-driven mean in practice here?

Answer outline:
- Steps emit structured outputs, but they do not mark themselves complete on return
- Each step runs a dedicated verifier that checks structure and branch justification
- Checkpoint phase transitions depend on verifier status, not just on tool success

### How is this inspired by Claude Code without being a clone?

Answer outline:
- I borrowed mature harness ideas: durable skills, transcripts, resumability, approval boundaries
- I did not copy product behavior, UI, or code-agent functionality
- The adaptation is incident-response oriented and intentionally Pythonic and contract-first

### Why stop at an approval-gated action stub?

Answer outline:
- Executing changes safely requires stronger controls than proposing them
- The milestone proves action candidacy, approval state, and replay without overclaiming autonomy
- It keeps risky behavior out of scope until the artifact and verifier layers are stronger

### What tradeoffs did you make?

Answer outline:
- Chose narrow deterministic slices over breadth and fancy model behavior
- Used fixed fixtures and replay coverage instead of broad integration surface
- Deferred planners, external integrations, and execution features to keep the harness legible

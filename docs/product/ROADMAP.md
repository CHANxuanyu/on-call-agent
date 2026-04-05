# Product Roadmap

This roadmap is intentionally narrow. It assumes the current runtime foundation stays intact and
product work continues to wrap that runtime instead of replacing it.

## Phase 1: Operator Console

Goal:
Provide a stronger operator workspace over the existing runtime.

Scope:

- sessions view
- incident detail view
- transcript, verifier, and checkpoint timeline
- approval and deny actions
- verification result display
- handoff export access

Exit signal:
An operator can manage the current deployment-regression flow from one product surface without
losing runtime truth or approval visibility.

## Phase 2: Second Incident Family

Goal:
Prove the product and runtime can support a second narrow incident family without collapsing into
generic orchestration.

Scope:

- one additional incident family
- explicit evidence, hypothesis, action candidate, and verifier chain for that family
- product surfaces updated to show the second family honestly

Exit signal:
The repository supports two narrow incident families with clear boundaries, verifier-backed
progression, and no hidden autonomy expansion.

## Phase 3: Metrics / Policy / Product Surface

Goal:
Deepen product credibility through policy visibility, evaluation, and operator-facing reporting.

Scope:

- clearer policy and autonomy explainability
- stronger evaluator and metrics surfacing
- more polished operator product surfaces built on the same runtime truth

Exit signal:
The product is easier to trust and assess because safety policy, replay/eval outcomes, and runtime
state are more visible to operators and reviewers.

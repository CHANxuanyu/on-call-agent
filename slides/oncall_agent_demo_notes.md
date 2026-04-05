# On-Call Agent Demo Notes

## 30-second version

This project is a verifier-driven incident-response runtime, not a generic chatbot or a mature ops
platform. The current repository proves one honest live path: detect a recent deployment
regression, gather evidence from a demo target, produce an approval-gated rollback candidate,
execute one bounded rollback after approval, and verify recovery from external runtime state. The
operator shell is a thin product layer over the same checkpoints, transcripts, and handoff/audit
surfaces.

## 2-minute version

The main idea is that incident handling needs more than a model that can call tools. You need
durable state, approval boundaries for risky actions, and a verifier story that checks whether the
environment actually recovered.

In this repository, the runtime chain is explicit: triage, follow-up, evidence, hypothesis,
recommendation, and an approval-gated action stub. For one narrow incident family,
`deployment-regression`, the approved branch continues into one bounded rollback and external
outcome verification. Everything is recorded through append-only transcripts and resumable
checkpoints, and the `SessionArtifactContext` reconstructs the durable artifacts for inspection,
handoff, and resume.

The operator shell sits on top of that runtime rather than replacing it. `manual` keeps the
operator in charge, `semi-auto` drives the read-only chain to the approval boundary, and
`auto-safe` only runs when a very narrow set of allowlist, policy, evidence, and version checks
pass. If those checks do not pass, it fails closed and degrades to `semi-auto` with a durable
reason.

The point is not breadth. The point is to show a believable harness for incident response with
explicit risk control and external verification.

## 5-minute version

I present this repository as a harness engineering project first and a product slice second. The
problem it targets is that ops or on-call automation is only credible if you can answer a few
questions clearly:

1. What state does the agent rely on?
2. Where is the approval boundary for risky actions?
3. What proves that remediation actually worked?
4. How do you resume or audit a session later?

The runtime is designed around those questions. It keeps control state in checkpoints, execution
history in append-only JSONL transcripts, and a small semantic incident snapshot in working
memory. `SessionArtifactContext` is the durable seam that reconstructs usable artifacts from that
state instead of treating chat history as the source of truth.

The implemented chain is intentionally explicit rather than generic orchestration:
triage, follow-up, evidence, hypothesis, recommendation, and action stub. That is the shared
spine for replay, inspection, and handoff. The live path stays narrow on purpose: for the
deployment-regression family, approval can unlock one bounded rollback against a local demo target,
and then the runtime re-probes external endpoints to verify recovery.

That is where the operator shell comes in. It is the product-facing surface that lets a reviewer
stay in one terminal and manage the lifecycle with commands like `/sessions`, `/resume`, `/status`,
`/why-not-auto`, `/approve`, `/verify`, and `/handoff`. But it is still thin. It does not create a
second state model. It uses the same runtime surfaces, the same approval seam, and the same
durable artifacts as the direct CLI.

I would emphasize three engineering choices in an interview:

- Verifier-driven progression: later stages are only considered complete when the matching verifier
  passes.
- Approval-gated mutation: the runtime treats risky writes as explicit policy decisions, not
  implicit autonomy.
- Durable recovery and audit: shell views, handoff export, and replay/eval all depend on the same
  structured state.

I would also be explicit about what it is not. It is not a broad ops platform, not a coding agent,
and not a claim that autonomous remediation is solved. It is one narrow but real demo-grade ops
agent path that is useful precisely because the scope is honest.

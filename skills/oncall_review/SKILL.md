+++
name = "oncall_review"
purpose = "Run a narrow, evidence-driven review and implementation workflow for a scoped harness slice."
when_to_use = "Use when review memory already exists and the user wants Codex to gather evidence, plan a slice, implement approved changes, or close review artifacts."
required_inputs = ["active review scope", "review checklist section or slice focus", "repository review memory"]
optional_inputs = ["accepted findings", "implementation order", "coding gate constraints", "prior slice decisions"]
expected_outputs = ["evidence package", "implementation plan", "implementation report", "docs closure update"]
verifier_expectations = ["findings are backed by repository evidence", "implementation stays within approved slice scope", "review docs reflect accepted closure state"]
permission_notes = ["do not code before explicit approval", "treat accepted findings and refinements as controlling constraints", "report repository-memory conflicts explicitly instead of guessing"]
examples = ["Review a scoped resume-semantics slice, implement only the accepted seam fixes, then close the review docs.", "Review a phase-boundary slice, fail closed on invalid state, and update checklist/log/decisions after acceptance."]
+++

# On-Call Review

## Goal

Turn an approved review slice into a reusable, auditable workflow for this repository.

## Roles

- user: approver, scope controller, final coding/docs gate
- architect/auditor: the reviewing authority that drives findings, accepted scope, and closure criteria
- Codex: implementer and evidence producer; reads repo state, gathers evidence, drafts plans, implements approved changes, runs tests, and updates review artifacts after acceptance

In this repository's current workflow, the architect/auditor role is typically played by ChatGPT.

## Read First

- `docs/review/REVIEW_SCOPE.md`
- `docs/review/REVIEW_CHECKLIST.md`
- `docs/review/REVIEW_LOG.md`
- `docs/review/DECISIONS.md`
- this skill file
- `AGENTS.md`

## Workflow

1. Scope alignment
   - Restate the active slice objective, in-scope boundaries, out-of-scope boundaries, and acceptance criteria from review memory.
   - If repository memory conflicts with the handoff, report the conflict explicitly and do not guess.

2. Evidence gathering
   - Inspect only the code and tests needed for the active checklist section.
   - Produce findings with:
     - finding id
     - severity
     - checklist item violated
     - evidence
     - why it matters
   - Prefer evidence over opinion and preserve fail-closed interpretation.

3. Implementation plan
   - Do not propose broad rewrites.
   - Organize the plan by accepted finding order.
   - For each finding, list:
     - files to modify
     - exact design change
     - acceptance criteria satisfied
     - tests to add/update
     - replay/fixture/checkpoint risk

4. Coding gate
   - Do not write code until the user explicitly approves the plan and any required refinements.
   - Treat the approved plan, ordering, and refinements as controlling implementation constraints.

5. Implementation report
   - After coding, report:
     - change summary by finding
     - files changed
     - tests added/updated
     - test results
     - replay/fixture/checkpoint churn
     - remaining gaps against acceptance criteria

6. Docs closure
   - Only after the user accepts the slice, update the review artifacts named by the user.
   - Record accepted findings, checklist completion state, decision notes, validation evidence, and explicitly preserved unchanged scope.
   - Keep deferred items untouched unless the accepted slice changed them.

## Operating Rules

- Keep scope narrow to the active slice.
- Preserve the verifier-driven, durable, approval-gated runtime narrative.
- Prefer small, auditable changes.
- Do not invent workflow steps, redesigns, or taxonomy changes that were not approved.
- Distinguish committed durable truth from inferred or display-only state.
- Treat malformed, ambiguous, or out-of-scope state conservatively and fail closed.
- Keep implementation and reporting aligned to accepted findings, not to speculative cleanup.
- Stop at the requested phase boundary: evidence only, plan only, coding report only, or docs closure only.

## Output Contracts

- Evidence package: scope restatement, files inspected, findings, proposed minimal changes, risks/tradeoffs, and any slice-specific appendix.
- Implementation plan: no code, only actionable design under approved ordering.
- Implementation report: implementation facts tied back to accepted findings.
- Docs closure report: summary of docs changed, exact checklist state, unresolved follow-up items.

## Definition of Done

A review slice is complete when:

- accepted findings are implemented or explicitly deferred as approved
- targeted tests pass and broader regression is reported where needed
- replay/fixture/checkpoint churn is called out explicitly
- review docs are updated to the accepted closure state
- intentionally unchanged scope remains explicit

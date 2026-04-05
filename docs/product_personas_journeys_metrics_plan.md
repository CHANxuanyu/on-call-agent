# Product Personas / Journeys / Metrics Plan

## Scope

Add three product-facing documents that make the repository easier to understand as a narrow
operator product:

- `docs/product/PERSONAS.md`
- `docs/product/USER_JOURNEYS.md`
- `docs/product/METRICS.md`

The documents must stay aligned with the current repository truth:

- `On-Call Copilot` is an incident decision and verification product
- current live scope is one `deployment-regression` incident family
- the product is panel-first, with a session-scoped assistant as a secondary surface
- rollback remains bounded and approval-gated
- recovery remains verifier-backed and externally checked

## Planned Content

1. `PERSONAS.md`
   - primary on-call operator persona
   - secondary incident commander / approver and next-shift operator personas
   - what each persona needs from the current product slice
   - why they would not use a generic coding agent for this moment
   - who the product is not for yet

2. `USER_JOURNEYS.md`
   - three journeys only:
     - page to decision-ready understanding
     - approval-gated action to recovery verification
     - handoff / shift continuity
   - each journey will include user, preconditions, main flow, bounded failure modes,
     product value, current limits, and clearly labeled future work
   - include short sections on why the product is not chat-first and not a coding workflow

3. `METRICS.md`
   - north star centered on time to safe decision-ready state
   - supporting metrics for decision velocity, approval flow, verification clarity, handoff,
     explainability, and bounded-action safety
   - demo-stage proxy metrics only, with explicit note that this is not production telemetry yet
   - explicit list of what not to optimize yet

## Constraints To Preserve

- no broader incident-family claims
- no generic autonomous-planner framing
- no product claims that outrun current runtime truth
- keep the Claude Code distinction crisp and reusable
- write for internal product clarity, recruiter readability, and interview usefulness

## Verification

- review the new docs together for terminology consistency
- tighten any wording that implies mature production telemetry, broad autonomy, or a chat-first UI

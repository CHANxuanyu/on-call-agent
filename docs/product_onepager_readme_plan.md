# Product One-Pager / README Plan

## Scope

Add one recruiter-readable product entry document and make the README expose the existing product
docs more clearly.

This slice must preserve the current repository truth:

- verifier-driven, durable, approval-gated incident-response runtime
- one narrow live `deployment-regression` product loop
- panel-first operator console and shell surfaces
- session-scoped assistant as a secondary explainer surface
- no broad autonomy, no generic coding-agent framing, no mature-product overclaim

## Planned changes

1. Add `docs/product/ONE_PAGER.md`
   - concise product overview for recruiting, interviews, and quick orientation
   - keep structure around problem, users, product surface, core value, safety model, honest
     scope, and near-term roadmap
   - reuse the current Claude Code distinction and current narrow product boundary

2. Update `README.md`
   - add a short product-orientation sentence near the top / Start Here
   - add product-facing entry links in `Start Here`
   - optionally add a small `Product Docs` group under `Deeper Docs`
   - preserve all existing limitation and runtime-first language

3. Consistency pass
   - keep wording aligned with `PRODUCT_BRIEF.md`, `POSITIONING.md`, `PERSONAS.md`,
     `USER_JOURNEYS.md`, and `METRICS.md`
   - tighten any language that sounds broader, more autonomous, or more mature than the repo
     actually is

## Non-goals

- no runtime changes
- no shell or console behavior changes
- no product-claim expansion beyond the current repo truth
- no README rewrite into a marketing page

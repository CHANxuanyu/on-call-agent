## Product Docs Plan

1. Add a new `docs/product/` directory with five narrow contract documents:
   - `PRODUCT_BRIEF.md` as the controlling product spec
   - `PRODUCT_PRINCIPLES.md` for implementation-facing product rules
   - `PHASE1_OPERATOR_CONSOLE_PRD.md` for the current product slice
   - `POSITIONING.md` for crisp Claude Code comparison language
   - `ROADMAP.md` for three bounded product phases
2. Keep all wording aligned with `README.md`, `AGENTS.md`, and `docs/architecture.md`:
   - verifier-driven, durable, approval-gated incident-response runtime
   - single-scenario, demo-grade ops agent
   - operator-facing On-Call Copilot
   - narrow deployment-regression scope
3. Update `AGENTS.md` so future coding agents must read `README.md`, `AGENTS.md`,
   `docs/architecture.md`, and `docs/product/PRODUCT_BRIEF.md` first, and must preserve the
   operator-copilot boundaries and approval/runtime seams.
4. Do not change runtime behavior, shell behavior, schemas, or implementation scope in this
   slice. End with a consistency review only.

# Documentation Polish Plan

Scope: tighten the repository's product-facing story and operator docs without changing runtime
behavior, shell behavior, or technical claims.

## Planned Changes

1. Align the top-level framing in `README.md`, `docs/usage.md`, `docs/demo.md`, and
   `docs/architecture.md` around the current honest state:
   - verifier-driven, durable, approval-gated incident-response runtime
   - one live externally verified deployment-regression path
   - operator shell with `manual`, `semi-auto`, and fail-closed `auto-safe`
   - not a mature ops product or broad autonomous platform

2. Tighten operator-facing guidance:
   - make the shell the clearest primary operator surface
   - simplify any duplicated or awkward command guidance
   - ensure autonomy-mode wording is consistent and technically honest
   - add clearer cross-links between the README, usage guide, demo guide, and smoke checklist

3. Fix remaining presentation drift in summary-style docs that still shape first impression:
   - update `docs/project_summary.md`
   - correct stale wording in operator/smoke or interview-facing overview text only where it now
     conflicts with the implemented bounded rollback demo path

4. Add a brief repo-facing notes file at `docs/repo_presentation_notes.md` capturing:
   - what was improved in this doc slice
   - what still remains intentionally narrow or imperfect
   - what should be cleaned up later, if anything

5. Run focused verification for the touched docs only:
   - inspect the final text for consistency
   - confirm links/commands still match the current shell and CLI surface

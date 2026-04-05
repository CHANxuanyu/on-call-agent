# 1. Design summary

This was a documentation-only product-narrative slice. The goal was to make the repository read as
one coherent, technically honest project: a verifier-driven, durable, approval-gated
incident-response runtime with one demo-grade live deployment-regression path, a thin operator
shell, and narrow `manual`, `semi-auto`, and fail-closed `auto-safe` modes. The runtime, shell,
and autonomy behavior were left unchanged.

# 2. What changed

- Tightened the first-impression framing in `README.md` so it now states clearly what the
  repository is today, what it is not, and where a reviewer should start.
- Improved operator-facing guidance and cross-linking in `docs/usage.md`, `docs/demo.md`, and
  `docs/operator_shell_smoke_checklist.md`.
- Updated `docs/architecture.md` and `docs/project_summary.md` so they reflect the current bounded
  live rollback path and the thin shell layer without overstating product maturity.
- Corrected stale wording in `docs/interview.md`, `docs/interview_mastery_guide.md`,
  `docs/resume.md`, and `docs/claude_code_comparison.md` where the repo still read like it never
  executed any remediation at all.
- Added the scoped implementation plan in `docs/doc_polish_plan.md`.
- Added a concise follow-up issue summary in `docs/repo_presentation_notes.md`.

# 3. Why this is safe

This slice only changes text. It preserves the existing runtime seams, verifier-backed progression,
approval boundaries, transcript/checkpoint semantics, `SessionArtifactContext` recovery model, and
current shell/autonomy behavior. The edits remove stale or inconsistent claims rather than changing
scope or inflating capability.

# 4. Files added

- `docs/doc_polish_plan.md`
- `docs/repo_presentation_notes.md`

# 5. Files touched

- `README.md`
- `docs/usage.md`
- `docs/demo.md`
- `docs/architecture.md`
- `docs/project_summary.md`
- `docs/operator_shell_smoke_checklist.md`
- `docs/claude_code_comparison.md`
- `docs/interview.md`
- `docs/interview_mastery_guide.md`
- `docs/resume.md`

# 6. Remaining repo presentation issues

- The repository still has several historical milestone plans and reports in `docs/` that are
  useful development records but not ideal onboarding docs.
- The operator/product story is now consistent, but it is still spread across multiple files
  instead of one short docs landing page.
- The live product story remains intentionally narrow: one incident family, one bounded rollback
  action, and one local demo target.

# 7. Verification performed

- Audited the current product-facing docs before editing and wrote the scoped plan first.
- Ran consistency sweeps across `README.md` and `docs/` to find stale wording and conflicting
  claims.
- Checked the current CLI surface with `python -m runtime.cli --help`.
- Checked the current shell surface with `python -m runtime.cli shell --help`.
- Reviewed the final diff for the touched documentation files.
- No runtime tests were run because this slice changed documentation only.

# 8. Suggested commit message

`Polish repository framing and operator-facing documentation`

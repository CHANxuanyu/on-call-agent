# Repo Presentation Notes

## What Improved

- README, usage, demo, and architecture docs now describe the same current product slice:
  verifier-driven runtime, one live deployment-regression demo path, and the operator shell with
  `manual`, `semi-auto`, and fail-closed `auto-safe`.
- Stale wording that implied the repository still stopped everywhere at the action stub was
  corrected in the summary, interview, and resume-facing docs.
- The shell smoke checklist is now linked more clearly from the main operator docs.

## What Still Remains Imperfect

- The repo still has several long-form historical notes and milestone reports that are useful for
  development history but are not ideal onboarding docs.
- The operator story is honest but still spread across multiple files rather than one short docs
  landing page.
- The current live path is intentionally single-scenario and local-demo-target only.

## Later Fixes Worth Considering

- Add one small docs index if the number of top-level docs keeps growing.
- Add lightweight link-checking or docs consistency checks if the command surface changes more
  often.

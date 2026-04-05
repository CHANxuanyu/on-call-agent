# 1. Design summary

This slice turns the existing operator shell into a more session-centric workspace without adding a
new runtime or state layer. The new shell commands stay anchored to the repository's durable seams:
checkpoint files, append-only transcripts, and `SessionArtifactContext` reconstruction. Session
listing, indexed resume, richer compact status, mode explainability, and recent activity all sit as
thin product features over the current verifier-driven, approval-gated runtime.

# 2. What changed

- Added a short implementation plan at `docs/session_workspace_plan.md` and implemented only that
  scope.
- Extended `src/runtime/shell.py` with session workspace commands:
  - `/sessions [--limit <n>]` to list recent sessions from durable checkpoint and transcript state
  - `/resume <session-id|index>` to resume by explicit id or the numeric order shown by
    `/sessions`
  - richer `/status` output with session and incident identity, family, phase, current step,
    requested and effective mode, downgrade reason, approval state, next action, evidence summary,
    latest verifier summary, handoff availability, and last-updated time
  - `/why-not-auto` and `explain-mode` alias to explain current requested mode, effective mode,
    downgrade reason, target allowlist status, current auto-safe eligibility, and the gate
    conditions that passed, failed, or remain unknown
  - `/tail [--limit <n>]` to show recent operator-relevant transcript activity such as checkpoint
    writes, approval resolution, verifier outcomes, and rollback or outcome tool results
- Added lightweight session workspace helpers in `src/runtime/shell.py`:
  - compact durable session summary assembly from checkpoint plus transcript files
  - operator-friendly session list rendering
  - recent activity filtering over existing transcript events
  - structured auto-safe gate condition reporting for explainability
- Added focused unit coverage in `tests/unit/test_runtime_shell.py` for:
  - recent session listing
  - indexed resume behavior
  - richer `/status` rendering
  - `/why-not-auto` output
  - `/tail` recent activity output
- Updated the operator-facing docs to surface the new workspace commands and workflow:
  - `README.md`
  - `docs/usage.md`
  - `docs/demo.md`

# 3. Why this is safe

This slice does not redesign orchestration or create a second application layer. The shell still
uses the same live start, approval, verification, inspection, and handoff seams. Session discovery
reads checkpoint and transcript files directly instead of introducing hidden mutable UI state.
`/why-not-auto` reuses the existing narrow auto-safe gate rather than broadening autonomy. Approval
boundaries, transcript semantics, checkpoint semantics, verifier-backed progression, and
`SessionArtifactContext` recovery logic remain intact.

# 4. Files added

- `docs/session_workspace_plan.md`

# 5. Files touched

- `src/runtime/shell.py`
- `tests/unit/test_runtime_shell.py`
- `README.md`
- `docs/usage.md`
- `docs/demo.md`

# 6. Invariants preserved

- Existing direct CLI commands still work unchanged.
- The shell remains a thin operator layer over the current runtime rather than a second runtime.
- No new hidden state store was introduced; the shell continues to rely on checkpoints,
  transcripts, working memory, and handoff regeneration.
- Auto-safe remains narrow, fail-closed, and limited to the existing deployment-regression rollback
  path.
- Approval-gated execution still requires the same durable approval flow.
- Verifier-backed phase progression, transcript durability, checkpoint durability, and auditability
  were preserved.
- `SessionArtifactContext` remains the durable recovery and artifact reconstruction seam.

# 7. New operator workflow

1. Launch `oncall-agent shell`.
2. Run `/sessions` to discover recent durable sessions in a compact operator-facing list.
3. Use `/resume <index>` or `/resume <session-id>` to reactivate a prior session and
   automatically receive a compact summary.
4. Use `/status` as the default cockpit view for phase, mode, approval, evidence, verifier, and
   handoff state.
5. Use `/why-not-auto` to understand the current mode, any downgrade reason, allowlist status, and
   whether the current runtime state qualifies for auto-safe execution.
6. Use `/tail` to follow recent important activity without dumping the full audit trail.
7. Continue to use the existing `/inspect`, `/audit`, `/approve`, `/deny`, `/verify`, and
   `/handoff` commands when deeper inspection or action is required.

# 8. Verification performed

- `ruff check src/runtime/shell.py tests/unit/test_runtime_shell.py src/runtime/cli.py README.md docs/usage.md docs/demo.md docs/session_workspace_plan.md`
- `pytest tests/unit/test_runtime_shell.py tests/unit/test_runtime_cli.py tests/integration/test_runtime_shell_cli.py`
- Result: `14 passed, 5 skipped`
- The skipped tests are the existing live shell integration cases that require local TCP bind,
  which is unavailable in this sandbox.
- The new session workspace behaviors are covered in the shell unit suite, so the workspace slice
  was still verified locally without changing runtime semantics.

# 9. Remaining risks

- `/sessions` only reflects the checkpoint root the shell is currently pointed at, which is
  intentional but means sessions under other roots are not shown.
- Session discovery skips unreadable or invalid checkpoint files rather than surfacing them inline
  in the compact list.
- `/why-not-auto` remains conservative when live deployment state cannot be fetched, so operators
  may see `unknown` conditions when the demo target is unreachable.
- The existing live shell integration tests were skipped in this sandbox, so the full interactive
  path should still be exercised in an environment where local TCP bind is available.

# 10. Suggested commit message

`Add session workspace commands to the operator shell`

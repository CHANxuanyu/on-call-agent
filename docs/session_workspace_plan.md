# Session Workspace Plan

Scope: add a thin session-centric workspace layer to the existing operator shell without changing
runtime semantics, approval boundaries, transcript contracts, or checkpoint recovery seams.

Planned changes:

1. Add durable-state-backed session discovery helpers.
   - Implement a compact recent-session listing from checkpoint files only.
   - Reconstruct lightweight operator summaries with session id, incident id, family, phase, mode,
     approval state, latest verifier summary, and last updated time.

2. Extend the shell with session workspace commands.
   - Add `/sessions` for recent session listing.
   - Improve `/resume` to accept either an explicit session id or a short index from `/sessions`,
     then print a compact post-resume summary.
   - Add `/tail` for recent important transcript activity from the current session.
   - Add `/why-not-auto` for explicit mode and auto-safe gate explainability.

3. Tighten compact operator status output.
   - Expand `/status` to consistently show identity, phase, step, requested/effective mode,
     downgrade reason, approval state, next action, evidence summary, latest verifier summary, and
     handoff availability.

4. Keep the shell thin over existing runtime seams.
   - Reuse `SessionArtifactContext`, checkpoint files, transcript events, and current auto-safe gate
     logic rather than introducing new state.
   - Add small shell/inspect helpers instead of a new application layer.

5. Add focused tests and docs.
   - Cover `/sessions`, indexed `/resume`, richer `/status`, `/why-not-auto`, and `/tail`.
   - Update `README.md`, `docs/usage.md`, and `docs/demo.md` to reflect the session workspace
     commands and operator flow.

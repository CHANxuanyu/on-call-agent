# README Polish Plan

## Goal

Make `README.md` a concise landing page that tells a new reviewer what the repository is, what it
can do today, what it intentionally does not do, and where to go next.

## Scope

1. Keep the current repo framing as source of truth:
   verifier-driven, durable, approval-gated incident-response runtime with one demo-grade live
   `deployment-regression` path and a thin operator shell.
2. Tighten the README top section so it clearly answers:
   what this project is, what it can do now, what it is not, and where to start.
3. Restructure the README around short landing-page sections:
   start here, current capabilities, quickstart, operator shell, live demo flow, autonomy modes,
   and honest scope.
4. Remove or compress README material that belongs in deeper docs and replace it with links to
   `docs/usage.md`, `docs/demo.md`, and `docs/architecture.md`.
5. Keep terminology consistent with the current docs and avoid any new product claims.

## Non-Goals

- no runtime, shell, or test changes
- no documentation rewrite outside `README.md`
- no broader product positioning or maturity claims

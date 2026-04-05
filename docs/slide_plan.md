# Slide Plan

## Goal

Create one concise Beamer deck plus speaking notes that present the repository as it exists today:
a verifier-driven, durable, approval-gated incident-response runtime with one demo-grade live
deployment-regression path and a thin operator shell.

## Scope

1. Use `README.md`, `docs/usage.md`, `docs/demo.md`, `docs/architecture.md`, and
   `docs/project_summary.md` as source-of-truth framing.
2. Add `slides/oncall_agent_demo.tex` with a small interview/demo deck:
   title, problem framing, what the project is, architecture, live loop, shell/modes,
   credibility, intentional limits, demo flow, tradeoffs/next steps.
3. Add `slides/oncall_agent_demo_notes.md` with 30-second, 2-minute, and 5-minute speaking
   versions aligned to the deck.
4. Keep terminology consistent with the repository:
   verifier-driven, durable state, approval-gated rollback, external outcome verification,
   operator shell, `manual` / `semi-auto` / `auto-safe`.
5. Verify that the LaTeX source is structurally sound and, if the toolchain is available,
   compile it once without adding new dependencies.

## Non-Goals

- no runtime or shell changes
- no product repositioning beyond the current docs
- no fabricated benchmarks or maturity claims
- no custom LaTeX framework beyond standard Beamer packages

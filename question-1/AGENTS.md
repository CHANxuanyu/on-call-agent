# AGENTS.md

## Project Summary

This repository is an interview-style On-Call Assistant web app with three phases under separate route prefixes: `/v1` lexical retrieval, `/v2` semantic retrieval, and `/v3` a constrained dialogue layer over the SOP corpus in `data/`.

## Highest-Priority Rule

`README.md` is the controlling specification. If any local assumption, old note, or future request conflicts with `README.md`, follow `README.md`.

## Repository Map

### Core specs and design docs

- `README.md`
  Primary product and acceptance specification.
- `docs/phase1.md`
  Phase 1 technical design.
- `docs/phase2.md`
  Phase 2 technical design.
- `docs/phase3.md`
  Phase 3 technical design.
- `docs/HANDOFF.md`
  Current project status and future-session handoff notes.

### App entry points

- `app/main.py`
  Shared FastAPI app wiring and startup behavior.
- `app/api/v1.py`
  Phase 1 HTTP/UI routes.
- `app/api/v2.py`
  Phase 2 HTTP/UI routes.
- `app/api/v3.py`
  Phase 3 chat routes.

### Key services and agent files

- `app/services/document_service.py`
  Phase 1 lexical ingestion and search orchestration.
- `app/services/semantic_search_service.py`
  Phase 2 semantic retrieval orchestration.
- `app/services/agent_service.py`
  Phase 3 session-aware chat entrypoint.
- `app/agent/loop.py`
  Phase 3 catalog-driven single-tool loop.
- `app/agent/tools.py`
  `readFile(fname)` safety boundary and `catalog.json` generation.
- `app/agent/memory.py`
  In-memory session storage.

### Key tests

- `tests/test_search_api.py`
  Phase 1 API contract.
- `tests/test_v2_behavior.py`
  Phase 2 retrieval behavior.
- `tests/test_v3_tools.py`
  Phase 3 tool safety and catalog generation.
- `tests/test_v3_agent_behavior.py`
  Phase 3 routing, grounding, follow-up, and low-confidence behavior.
- `tests/test_v3_api.py`
  Phase 3 API contract and session reuse.

### Useful scripts

- `scripts/benchmark_v1.py`
  Phase 1 benchmark.
- `scripts/smoke_v2.py`
  Manual Phase 2 verification with the real model.
- `scripts/diagnose_v2.py`
  Phase 2 query/chunking diagnostics.

## Current Architecture Snapshot

- `v1`
  In-memory lexical retrieval baseline over visible HTML text.
- `v2`
  In-memory semantic retrieval with chunking, hybrid support, warmup, and query rewrite.
- `v3`
  Catalog-driven, single-tool dialogue layer that routes via `catalog.json` and reads SOP files only through `readFile(fname)`.

## Non-Negotiable Constraints

- Do not violate `README.md`.
- Do not rewrite frozen Phase 1 or Phase 2 behavior without strong reason.
- Phase 3 must remain single-tool: `readFile(fname)`.
- No hidden retrieval inside the Phase 3 loop.
- No handwritten cheat routing file or README-example answer map.
- `catalog.json` is generated automatically; do not maintain it by hand.
- Tool traces must remain visible in `/v3`.
- Consulted files must remain visible in `/v3`.
- Do not add new dependencies without strong justification.

## Safe Working Rules

- Prefer small diffs over broad rewrites.
- Preserve current tests and add deterministic regression coverage for behavior changes.
- Update the relevant phase doc when design behavior changes materially.
- Keep docs factual and do not overclaim agent autonomy.
- For Phase 3 work, inspect `app/agent/loop.py`, `app/agent/tools.py`, and `tests/test_v3_agent_behavior.py` first.

## Verification Commands

```bash
pytest
uvicorn app.main:app --reload
python scripts/smoke_v2.py
python scripts/diagnose_v2.py
```

## Manual Checks

- `/v1` should still behave as the lexical baseline.
- `/v2` should still behave as the semantic retrieval layer.
- `/v3` should show visible tool calls, consulted files, and catalog-first single-tool behavior.

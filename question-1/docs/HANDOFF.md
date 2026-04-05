# Handoff

## Current Project Status

- Phase 1: complete and treated as frozen.
- Phase 2: complete and treated as frozen.
- Phase 3: current dialogue layer, implemented as a catalog-driven single-tool workflow over the SOP corpus.

## What Changed Most Recently

The main current Phase 3 truth is:

- the Phase 3 loop no longer uses hidden semantic retrieval for routing
- routing is now driven by generated `catalog.json`
- `catalog.json` is the routing index for Phase 3
- the only actual tool boundary is `readFile(fname)`
- answers are grounded in files actually read
- low-confidence behavior is conservative and may stop after reading only `catalog.json`

## Key Constraints That Must Not Regress

- `README.md` is the controlling spec.
- Phase 3 must remain single-tool: `readFile(fname)`.
- No hidden retrieval inside `app/agent/loop.py`.
- No handwritten route map or cheat answer file.
- No dependency creep without a strong reason.
- Tool trace must remain visible.
- Consulted files must remain visible.
- `catalog.json` must remain generated, not hand-maintained.

## Key Files To Inspect First

- `README.md`
- `AGENTS.md`
- `docs/HANDOFF.md`
- `docs/phase1.md`
- `docs/phase2.md`
- `docs/phase3.md`
- `app/agent/loop.py`
- `app/agent/tools.py`
- `app/services/agent_service.py`
- `tests/test_v3_agent_behavior.py`

## Known Limitations

- Phase 3 routing is heuristic and catalog-driven, not learned.
- There is no persistent memory.
- There is no live LLM planning loop in the current runtime path.
- The Phase 3 loop is constrained and mostly deterministic.
- Catalog quality materially affects Phase 3 routing quality.

## Recommended Workflow For Future Modifications

1. Read `README.md`.
2. Read `AGENTS.md`.
3. Read `docs/HANDOFF.md`.
4. Read the relevant phase technical doc.
5. Inspect the main code path for that phase.
6. Make the smallest change that satisfies the requirement.
7. Add or update deterministic tests for regressions.
8. Run verification commands.
9. Update docs if behavior or design changed materially.

## Quick Verification Checklist

```bash
pytest
python scripts/smoke_v2.py
uvicorn app.main:app --reload
```

Manual `/v3` checks:

- ask `数据库主从延迟超过30秒怎么处理？`
- ask `服务 OOM 了怎么办？`
- ask `P0 故障的响应流程是什么？`
- ask `怀疑有人入侵了系统`
- ask `推荐结果质量下降了`

Confirm:

- `catalog.json` is read first
- tool trace is visible
- consulted files are visible
- answers are grounded in files actually read

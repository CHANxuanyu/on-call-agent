# Architecture Overview

Back to the main entry: [README.en.md](../README.en.md)

## 1. One-sentence summary

`question-1` is a single FastAPI application that serves v1 keyword search, v2 semantic search, and a constrained v3 agent in one process, while using startup to load documents, warm the semantic index, and generate the catalog.

## 2. Evolution path

The project evolves in a deliberate sequence:

1. `v1`
   turn HTML into clean, searchable visible text
2. `v2`
   add semantic retrieval on top of the v1 baseline
3. `v3`
   add a constrained “find files + read files + answer” workflow

A simplified mental model:

```text
v1: find the document
v2: find the right document even when wording drifts
v3: read the right document and answer with grounding
```

## 3. Startup flow

The app entrypoint is [app/main.py](../app/main.py).

During startup, the app does four main things:

1. load `data/*.html` into the v1 `DocumentService`
2. load the same HTML files into the v2 `SemanticSearchService`
3. call `semantic_service.warmup()`
4. call `AgentService.ensure_catalog()` to generate `data/catalog.json` for v3

Flow:

```text
data/*.html
  -> DocumentService (v1 lexical index)
  -> SemanticSearchService (v2 chunks + embeddings)
  -> AgentService.ensure_catalog() (v3 catalog.json)
  -> app ready
```

## 4. Request paths

### v1 request path

```text
POST /v1/documents
  -> app/api/v1.py
  -> DocumentService.ingest_document(...)
  -> HTML parser
  -> tokenizer
  -> BM25 lexical index
```

```text
GET /v1/search
  -> app/api/v1.py
  -> DocumentService.search(...)
  -> BM25 lexical index
  -> JSON results
```

### v2 request path

```text
GET /v2/search
  -> app/api/v2.py
  -> SemanticSearchService.search(...)
  -> optional query rewrite
  -> semantic chunk search
  -> lexical fusion with the v1 service
  -> document aggregation
  -> JSON results
```

### v3 request path

```text
POST /v3/chat
  -> auth dependency
  -> rate-limit dependency
  -> AgentService.chat(...)
  -> AgentLoop or LLMAgentLoop
  -> readFile("catalog.json")
  -> select SOP file(s)
  -> readFile("sop-xxx.html")
  -> grounded answer
  -> tool_calls + consulted_files + history
```

```text
GET /v3/history/{session_id}
  -> auth dependency
  -> AgentService.get_history(...)
  -> in-memory session lookup
  -> history JSON
```

## 5. Main module responsibilities

| Module | Directory | Responsibility |
| --- | --- | --- |
| API layer | `app/api/` | routes, request validation, response mapping |
| Core model | `app/core/` | HTML parsing and Pydantic schemas |
| Data store | `app/data_store/` | in-memory document storage |
| Indexing layer | `app/indexing/` | tokenizer, BM25, chunker, semantic index |
| Service layer | `app/services/` | orchestration for v1/v2/v3 |
| Agent layer | `app/agent/` | v3 loop, tool, memory, prompting |
| Security layer | `app/security/` | API-key auth and rate limiting |
| Observability layer | `app/observability/` | JSON logs, metrics, request/trace middleware |

## 6. Data and state

Most state in the current version is in memory:

- v1 document index: in memory
- v2 semantic index: in memory
- v3 sessions: in memory
- `/v3/chat` rate-limit windows: in memory

Main files on disk:

- `data/*.html`
- `data/catalog.json`

Implications:

- a restart clears runtime session and rate-limit state
- the v3 catalog is regenerated at startup

## 7. Security boundary

The current security model is intentionally minimal, not production-complete:

- `POST /v1/documents`, `POST /v3/chat`, and `GET /v3/history/{session_id}` are protected by `API_KEY`
- clients pass it through `X-API-Key`
- the `X-API-Key` input on `/v3` expects this same value, not `OPENAI_API_KEY`
- if `API_KEY` is not configured, development mode allows the requests but logs a startup warning
- `/v3/chat` has a simple per-IP rate limit
- `readFile(fname)` rejects absolute paths and path traversal

Unprotected endpoints:

- `/healthz`
- `/readyz`
- `/metrics`

## 8. Observability

The app mounts `ObservabilityMiddleware`, which provides:

- generated or propagated `X-Request-ID`
- generated or propagated `X-Trace-ID`
- JSON logging
- Prometheus metrics
- `healthz` and `readyz`
- JSON-wrapped unhandled exceptions

The local observability stack can be started with [docker-compose.observability.yml](../docker-compose.observability.yml):

- app
- Prometheus
- Grafana

## 9. Environment variables

Most commonly used:

- `API_KEY`
- `RATE_LIMIT_PER_MIN`
- `OPENAI_API_KEY`
- `LOG_LEVEL`

Used for v2 tuning:

- `V2_SCORE_EXPERIMENT_PRESET`
- `V2_QUERY_VARIANT_MERGE_STRATEGY`
- `V2_DISPLAY_SCORE_TEMPERATURE`
- `V2_FUSION_DENSE_WEIGHT`
- `V2_FUSION_LEXICAL_WEIGHT`

See [.env.example](../.env.example) for a copyable sample.

## 10. The most important design trade-offs

### Single app instead of split services

Benefits:

- easier interview walkthrough
- simpler local startup
- easier reuse of shared structures across phases

Costs:

- state stays inside one process
- the architecture is more demo-oriented than production-distributed

### In-memory instead of persistent state

Benefits:

- shorter code paths
- easier tests
- easier to explain during review

Costs:

- not suitable for true high-availability deployment
- runtime state disappears on restart

### Constrained agent instead of free-form autonomous agent

Benefits:

- more predictable behavior
- clearer safety boundary
- stable tests

Costs:

- lower extensibility ceiling
- strong dependence on catalog quality

## 11. The most reasonable next steps

1. add persistence or shared storage for documents, sessions, and rate limits
2. let the v3 catalog refresh incrementally
3. replace per-process rate limiting with shared rate limiting
4. add offline evaluation and a replaceable vector backend for v2
5. add real integrations for v3 instead of stopping at `readFile`

# On-Call Agent `question-1`

This is the onboarding guide for the interview project. After reading this file, a new teammate should be able to do the following in 10 to 15 minutes:

- create a virtual environment and install dependencies
- start the FastAPI service and open `/v1`, `/v2`, and `/v3`
- call the v1, v2, and v3 APIs with `curl`
- understand why the project evolves from v1 to v3
- run `ruff` and `pytest`

Chinese version: [README.md](./README.md).

## Quickstart

1. Enter the directory and create a virtual environment

```bash
cd question-1
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies

```bash
pip install -r requirements.txt
```

If you want a single-command local start after dependencies are installed:

```bash
./scripts/start.sh
```

3. Set the minimum runtime environment and start the service

```bash
export API_KEY=dev-secret
export RATE_LIMIT_PER_MIN=30
uvicorn app.main:app --reload
```

4. Open the pages

- `http://127.0.0.1:8000/v1`
- `http://127.0.0.1:8000/v2`
- `http://127.0.0.1:8000/v3`
- `http://127.0.0.1:8000/docs`

5. Use a second terminal for a one-minute verification

```bash
curl http://127.0.0.1:8000/healthz
curl 'http://127.0.0.1:8000/v1/search?q=OOM'
curl 'http://127.0.0.1:8000/v2/search?q=服务器挂了'
curl -X POST 'http://127.0.0.1:8000/v3/chat' \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: dev-secret' \
  -d '{"message":"服务 OOM 了怎么办？"}'
```

6. Run quality checks

```bash
ruff check .
pytest -q
```

You can also use the one-command test wrapper:

```bash
./scripts/test.sh
./scripts/test.sh --smoke
```

## Table of Contents

- [Project Overview](#project-overview)
- [Feature Matrix](#feature-matrix)
- [Repository Layout](#repository-layout)
- [Environment Requirements](#environment-requirements)
- [Install Dependencies](#install-dependencies)
- [Run Locally](#run-locally)
- [One-Minute Verification](#one-minute-verification)
- [Browser Pages and API Examples](#browser-pages-and-api-examples)
- [Docker and Observability Stack](#docker-and-observability-stack)
- [Testing and Quality Checks](#testing-and-quality-checks)
- [Security Configuration](#security-configuration)
- [Observability](#observability)
- [FAQ / Troubleshooting](#faq--troubleshooting)
- [Limitations & Next Steps](#limitations--next-steps)
- [Documentation Map](#documentation-map)

## Project Overview

`question-1` is an On-Call SOP assistant that evolves across three phases:

- `v1`: keyword search, to solve “find the right SOP first”
- `v2`: semantic search, to solve “the user wording does not exactly match the SOP text”
- `v3`: a constrained agent, to answer in chat form and show the actual file reads and tool traces
- the `v3` page now renders the current session timeline and can use `X-API-Key` to access protected chat endpoints

The default corpus lives under [data/](./data). On startup, the app automatically:

- loads `data/*.html` into the v1 lexical index
- loads the same corpus into the v2 semantic index and warms it up
- generates [data/catalog.json](./data/catalog.json) for v3

The design trade-offs are explicit:

- keep a single FastAPI app for local demos and interview review
- keep indexes and sessions in memory for simplicity
- use a rule-based, catalog-first flow for v3 by default; only try the LLM loop when `OPENAI_API_KEY` is set

## Feature Matrix

| Dimension | v1 | v2 | v3 |
| --- | --- | --- | --- |
| Goal | Keyword retrieval | Semantic retrieval | Chat-style SOP assistant |
| Route prefix | `/v1` | `/v2` | `/v3` |
| Main APIs | `GET /v1/search`, `POST /v1/documents` | `GET /v2/search` | `POST /v3/chat`, `GET /v3/history/{session_id}` |
| Page | `GET /v1` | `GET /v2` | `GET /v3` (chat page with timeline and `X-API-Key` input) |
| Core behavior | visible-text extraction + BM25-style ranking | chunk-level embeddings + lexical fusion | catalog-first routing + `readFile(fname)` + grounded answer |
| Typical query | `OOM`, `CDN`, `故障` | `服务器挂了`, `黑客攻击` | `数据库主从延迟超过30秒怎么处理？` |
| Requires exact token match | Yes | No | No |
| Shows tool trace | No | No | Yes |
| Protected endpoints | `POST /v1/documents` | None | `POST /v3/chat`, `GET /v3/history/{session_id}` |
| Auth method | `X-API-Key` | None | `X-API-Key` |
| Rate limiting | None | None | IP-based limit on `/v3/chat` |
| Session support | No | No | Yes, in-memory `session_id` plus `history` restore |
| Main limitation | depends on keyword overlap | first startup may download a model | no persistence, rate limiting is per-process |

## Repository Layout

```text
question-1/
├── app/
│   ├── api/                 # v1/v2/v3 routes
│   ├── agent/               # v3 agent loop, memory, tool, prompt
│   ├── core/                # HTML parsing and Pydantic schemas
│   ├── data_store/          # in-memory document store
│   ├── indexing/            # tokenizer, BM25, chunker, semantic index
│   ├── observability/       # JSON logging, metrics, request/trace middleware
│   ├── security/            # API key auth and rate limiting
│   ├── services/            # v1/v2/v3 service layer
│   └── main.py              # app entrypoint and startup wiring
├── data/                    # demo SOP corpus and catalog.json
├── docs/                    # bilingual version docs and architecture docs
├── monitoring/              # Prometheus, Grafana provisioning, alert rules
├── static/                  # frontend JS/CSS
├── templates/               # v1/v2/v3 page templates
├── tests/                   # pytest suite
├── Dockerfile
├── docker-compose.observability.yml
├── requirements.txt
└── ruff.toml
```

## Environment Requirements

- Python: `3.11+` recommended
- OS: macOS / Linux / WSL
- Docker: optional
- Network: the first v2 startup may need to download a sentence-transformer model

Additional notes:

- local development targets Python `3.11+`
- the provided [Dockerfile](./Dockerfile) uses `python:3.12-slim`
- `pytest` uses fake embedders and stubs by default, so tests do not require real OpenAI access or a real semantic model download

## Install Dependencies

Run these commands from `question-1/`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If you want to use the sample values from `.env.example`, copy it and export the values into the current shell:

```bash
cp .env.example .env
set -a
source .env
set +a
```

Important: the app does not load `.env` automatically. If you start `uvicorn` directly, you must `source` the file yourself or use `export`.

## Run Locally

Minimum startup command:

```bash
export API_KEY=dev-secret
export RATE_LIMIT_PER_MIN=30
uvicorn app.main:app --reload
```

If you do not set `API_KEY`:

- protected endpoints are allowed in development mode
- startup logs emit a warning saying production must set `API_KEY`

If you set `OPENAI_API_KEY`:

- v3 first tries the LLM loop
- if OpenAI setup fails, the code falls back to the default rule-based `AgentLoop`

```bash
export API_KEY=dev-secret
export RATE_LIMIT_PER_MIN=30
export OPENAI_API_KEY=''
uvicorn app.main:app --reload
```

After startup, you can access:

- pages: `/v1`, `/v2`, `/v3`
- health: `/healthz`
- readiness: `/readyz`
- metrics: `/metrics`
- OpenAPI: `/docs`

## One-Minute Verification

After the service starts, run this in another terminal:

```bash
curl http://127.0.0.1:8000/healthz
```

Expected response:

```json
{
  "status": "ok",
  "service": "On-Call Assistant",
  "version": "1.0.0"
}
```

Then verify all three versions:

```bash
curl 'http://127.0.0.1:8000/v1/search?q=OOM'
curl 'http://127.0.0.1:8000/v2/search?q=服务器挂了'
curl -X POST 'http://127.0.0.1:8000/v3/chat' \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: dev-secret' \
  -d '{"message":"数据库主从延迟超过30秒怎么处理？"}'
```

If all three commands return JSON, the following are working:

- the service itself
- the v1 lexical index
- the v2 semantic index
- the v3 chat path, auth, and rate-limiter

## Browser Pages and API Examples

### Browser pages

Open these URLs directly:

- `http://127.0.0.1:8000/v1`: keyword search page
- `http://127.0.0.1:8000/v2`: semantic search page
- `http://127.0.0.1:8000/v3`: chat assistant page with a conversation timeline, an `X-API-Key` input, and latest-turn tool-trace / consulted-file panels

### v1: ingest a document and run keyword search

The write endpoint requires `X-API-Key` only when `API_KEY` is configured.

```bash
curl -X POST 'http://127.0.0.1:8000/v1/documents' \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: dev-secret' \
  -d '{
    "id": "sop-custom",
    "html": "<html><head><title>Custom SOP</title></head><body><p>Primary &amp; backup path is active.</p></body></html>"
  }'
```

Sample response:

```json
{
  "id": "sop-custom",
  "title": "Custom SOP"
}
```

Search example:

```bash
curl 'http://127.0.0.1:8000/v1/search?q=backup'
```

Sample response:

```json
{
  "query": "backup",
  "results": [
    {
      "id": "sop-custom",
      "title": "Custom SOP",
      "snippet": "Primary & backup path is active.",
      "score": 1.0
    }
  ]
}
```

### v2: semantic search

```bash
curl 'http://127.0.0.1:8000/v2/search?q=服务器挂了'
curl 'http://127.0.0.1:8000/v2/search?q=黑客攻击'
curl 'http://127.0.0.1:8000/v2/search?q=机器学习模型出问题'
```

Sample response:

```json
{
  "query": "黑客攻击",
  "results": [
    {
      "id": "sop-005",
      "title": "信息安全 On-Call SOP",
      "snippet": "怀疑系统被入侵时，立即隔离主机，保全证据，轮换高风险凭证，并上报安全事件。",
      "score": 0.87
    }
  ]
}
```

### v3: chat-style agent

Browser-page notes:

- `/v3` is now a real chat page, not just a single-response panel
- the page keeps the current browser-session `session_id` and restores turns through `GET /v3/history/{session_id}`
- when backend auth is enabled, the `X-API-Key` input must contain the same `API_KEY` value, for example `dev-secret`
- this input is for the app's own API key, not `OPENAI_API_KEY`

First question:

```bash
curl -X POST 'http://127.0.0.1:8000/v3/chat' \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: dev-secret' \
  -d '{
    "message": "服务 OOM 了怎么办？"
  }'
```

Sample response:

```json
{
  "session_id": "4db3e4b9-4d14-4c03-bf85-2f31dbf43b5d",
  "assistant_message": "结论\n服务 OOM 时，先检查实例内存使用、最近发布记录和降级开关，再确认是否存在异常流量或大对象缓存。\n\n参考 SOP\n- sop-001.html",
  "tool_calls": [
    {
      "tool_name": "readFile",
      "arguments": {
        "fname": "catalog.json"
      },
      "status": "ok",
      "output_preview": "{\n  \"files\": ..."
    },
    {
      "tool_name": "readFile",
      "arguments": {
        "fname": "sop-001.html"
      },
      "status": "ok",
      "output_preview": "Title: 后端服务 On-Call SOP\nFile: sop-001.html\n..."
    }
  ],
  "consulted_files": [
    "sop-001.html"
  ],
  "history": [
    {
      "role": "user",
      "content": "服务 OOM 了怎么办？",
      "consulted_files": [],
      "tool_calls": []
    },
    {
      "role": "assistant",
      "content": "结论\\n服务 OOM 时，先检查实例内存使用、最近发布记录和降级开关，再确认是否存在异常流量或大对象缓存。\\n\\n参考 SOP\\n- sop-001.html",
      "consulted_files": [
        "sop-001.html"
      ],
      "tool_calls": [
        {
          "tool_name": "readFile",
          "arguments": {
            "fname": "catalog.json"
          },
          "status": "ok",
          "output_preview": "{\\n  \\\"files\\\": ..."
        }
      ]
    }
  ]
}
```

Follow-up question:

```bash
curl -X POST 'http://127.0.0.1:8000/v3/chat' \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: dev-secret' \
  -d '{
    "session_id": "4db3e4b9-4d14-4c03-bf85-2f31dbf43b5d",
    "message": "你刚才看了哪些文件？"
  }'
```

Fetch the current session history:

```bash
curl 'http://127.0.0.1:8000/v3/history/4db3e4b9-4d14-4c03-bf85-2f31dbf43b5d' \
  -H 'X-API-Key: dev-secret'
```

### Version documents

- [v1 中文](./docs/v1.zh.md)
- [v1 English](./docs/v1.en.md)
- [v2 中文](./docs/v2.zh.md)
- [v2 English](./docs/v2.en.md)
- [v3 中文](./docs/v3.zh.md)
- [v3 English](./docs/v3.en.md)

## Docker and Observability Stack

### Start the app container only

From `question-1/`:

```bash
docker build -t on-call-agent-question-1 .
docker run --rm -p 8000:8000 \
  -e API_KEY=dev-secret \
  -e RATE_LIMIT_PER_MIN=30 \
  on-call-agent-question-1
```

### Start app + Prometheus + Grafana

```bash
docker compose -f docker-compose.observability.yml up --build
```

Default ports:

- app: `http://127.0.0.1:8000`
- Prometheus: `http://127.0.0.1:9090`
- Grafana: `http://127.0.0.1:3000`

Default Grafana credentials:

- username: `admin`
- password: `admin`

This is a local demo configuration only, not a production setup.

## Testing and Quality Checks

### ruff

```bash
ruff check .
```

See [ruff.toml](./ruff.toml) for the configuration.

### pytest

```bash
pytest -q
```

If you want to chain `ruff`, `pytest`, and the optional HTTP smoke test:

```bash
./scripts/test.sh
./scripts/test.sh --smoke
```

The test suite covers:

- v1 HTML parsing, visible text extraction, and replacement semantics
- v2 semantic retrieval, hybrid fusion, startup warmup, and query rewrite
- v3 tool traces, grounding, follow-up behavior, chat-page history restore, and low-confidence handling
- health checks, metrics, request IDs, and trace IDs
- API-key auth, `GET /v3/history/{session_id}`, and `/v3/chat` rate limiting

### mypy

This repository does not currently configure `mypy`, and it is not part of CI.

### CI

The repository-level minimal CI lives at [../.github/workflows/ci.yml](../.github/workflows/ci.yml). Locally, the closest checks are:

```bash
ruff check .
pytest -q
```

## Security Configuration

See [.env.example](./.env.example) for a copyable sample.

| Environment variable | Default | Description |
| --- | --- | --- |
| `API_KEY` | empty | API key that protects write endpoints, `POST /v3/chat`, and `GET /v3/history/{session_id}` |
| `RATE_LIMIT_PER_MIN` | `30` | max requests per `client_ip` per minute for `/v3/chat` |
| `OPENAI_API_KEY` | empty | optional; if set, v3 tries the LLM loop |
| `LOG_LEVEL` | `INFO` | logging level |
| `V2_SCORE_EXPERIMENT_PRESET` | `baseline` | v2 score experiment preset |
| `V2_QUERY_VARIANT_MERGE_STRATEGY` | `weighted_sum` | `weighted_sum` / `max_score` / `top2_avg` |
| `V2_DISPLAY_SCORE_TEMPERATURE` | `1.0` | v2 display-score temperature |
| `V2_FUSION_DENSE_WEIGHT` | `0.7` | v2 dense-search weight |
| `V2_FUSION_LEXICAL_WEIGHT` | `0.3` | v2 lexical-search weight |

Currently protected endpoints:

- `POST /v1/documents`
- `POST /v3/chat`
- `GET /v3/history/{session_id}`

Endpoints that are neither authenticated nor rate-limited:

- `GET /healthz`
- `GET /readyz`
- `GET /metrics`

Operational notes:

- if `API_KEY` is not set, the service runs in development mode and logs a warning
- production must set `API_KEY`
- the `X-API-Key` input on `/v3` expects this `API_KEY` value, not `OPENAI_API_KEY`
- rate limiting is in-process, keyed by `client_ip`, and implemented as a simple sliding window
- with multi-process `uvicorn` or multiple replicas, rate limits are applied independently per process or replica

## Observability

### Health and readiness

- `/healthz`
  answers whether the process is alive
- `/readyz`
  answers whether startup, document loading, semantic warmup, and catalog generation are complete

Example:

```bash
curl http://127.0.0.1:8000/readyz
```

Sample response:

```json
{
  "ready": true,
  "checks": {
    "startup": {
      "ready": true,
      "detail": "startup complete"
    },
    "catalog": {
      "ready": true,
      "detail": "catalog path: /app/data/catalog.json"
    },
    "document_index": {
      "ready": true,
      "detail": "10 HTML document(s) loaded"
    },
    "semantic_index": {
      "ready": true,
      "detail": "10 HTML document(s) indexed for semantic search"
    }
  }
}
```

### Metrics

```bash
curl http://127.0.0.1:8000/metrics
```

Exported metrics include:

- HTTP request count and latency
- readiness status
- unhandled exceptions
- recommendation quality scores
- dependency latency

### Request / Trace IDs

If you send:

- `X-Request-ID`
- `X-Trace-ID`

the middleware echoes them back in the response headers. If you omit them, the service generates them automatically.

## FAQ / Troubleshooting

### 1. Why does `/readyz` return `503` right after startup?

Because the app still has to load HTML files, build the v2 semantic index, warm the model, and generate `catalog.json`. Until all checks are ready, `/readyz` returns `503`. This is expected.

### 2. Why is the first startup slow?

v2 depends on `sentence-transformers`. On the first real startup, the model may need to be downloaded into the local cache. Docker builds are also slower because PyTorch CPU wheels are large.

### 3. Can v3 work without `OPENAI_API_KEY`?

Yes. v3 works by default with the rule-based `AgentLoop`. `AgentService` only tries `LLMAgentLoop` when `OPENAI_API_KEY` is set.

### 4. Why do `POST /v1/documents`, `POST /v3/chat`, or `GET /v3/history/{session_id}` return `401`?

Because `API_KEY` is configured and your request did not provide the correct `X-API-Key` header. Verify:

```bash
export API_KEY=dev-secret
curl -H 'X-API-Key: dev-secret' ...
```

If you are using the browser page at `/v3`:

- the input box expects the app `API_KEY`, for example `dev-secret`
- do not paste `OPENAI_API_KEY` there

### 5. Why does the second `/v3/chat` request return `429`?

You hit the per-IP rate limit. Check whether `RATE_LIMIT_PER_MIN` is set too low. Tests often set it to `1` on purpose.

### 6. Why does v3 not see the document I just uploaded with `POST /v1/documents`?

Because v1 writes update the v1 and v2 in-memory indexes immediately, but they do not refresh the v3 catalog automatically. Restart the service so startup can regenerate `catalog.json`.

### 7. What if port `8000`, `9090`, or `3000` is already in use?

Either stop the existing process or change the port mapping. Examples:

- `uvicorn app.main:app --port 8001`
- `docker run -p 8001:8000 ...`

### 8. Why does `pytest -q` pass quickly even though real startup is slow?

Because the tests use fake embedders and stubs. They do not download the real sentence-transformer model and they do not call real OpenAI services.

### 9. I created a `.env` file. Why does `uvicorn` still not see the variables?

Because the repository does not auto-load `.env`. You must explicitly run:

```bash
set -a
source .env
set +a
```

### 10. What is the `X-API-Key` on the `/v3` page for?

It is the app's own shared API key for calling protected endpoints such as `/v3/chat` and `/v3/history/{session_id}`. It is not an OpenAI key.

- `X-API-Key` / `API_KEY`: access control for this app
- `OPENAI_API_KEY`: only used by the backend if it tries the OpenAI-powered v3 path

### 10. Which directory should I run commands from?

Unless a command says otherwise, this README assumes your current directory is `question-1/`.

## Limitations & Next Steps

The current implementation is strong for an interview artifact and local demo, but it is not a production on-call platform yet. Known limitations:

- indexes, sessions, and rate-limit state are all in memory by default
- `/v3/chat` rate limiting is single-process and IP-based
- v3 has only one tool, `readFile(fname)`, and no real external integrations
- `POST /v1/documents` does not refresh the v3 catalog automatically
- there is no persistence layer, background task queue, or multi-tenant auth model

The most valuable next steps are:

1. add persistence or shared state for documents, catalog, sessions, and rate limits
2. add incremental catalog refresh instead of requiring a restart
3. replace per-process rate limiting with Redis or gateway-level limiting
4. add real on-call integrations such as PagerDuty, Slack, or a ticket system
5. add offline evaluation, reranking, or a replaceable vector store for v2

## Documentation Map

Onboarding-focused bilingual version guides:

- [架构总览（中文）](./docs/architecture.zh.md)
- [Architecture Overview (English)](./docs/architecture.en.md)
- [v1 中文](./docs/v1.zh.md)
- [v1 English](./docs/v1.en.md)
- [v2 中文](./docs/v2.zh.md)
- [v2 English](./docs/v2.en.md)
- [v3 中文](./docs/v3.zh.md)
- [v3 English](./docs/v3.en.md)

Existing deeper technical design notes:

- [Phase 1 Technical Design](./docs/phase1.md)
- [Phase 2 Technical Design](./docs/phase2.md)
- [Phase 3 Technical Design](./docs/phase3.md)

# Phase 2 Technical Design

## Scope

This document covers Phase 2 only.

Phase 2 extends the Phase 1 keyword-search baseline with semantic retrieval over the same SOP HTML corpus. The implementation adds chunk-level dense retrieval, a minimal semantic web UI and API, startup-time semantic index warmup, and a small deterministic query rewrite layer for broad outage-style queries.

## Phase 2 Goals

Phase 2 focuses on five concrete goals:

1. Add semantic retrieval over the existing SOP HTML documents without replacing the Phase 1 lexical baseline.
2. Retrieve at chunk level rather than embedding whole documents.
3. Support non-exact-match queries where the user’s wording does not need to appear verbatim in the SOP text.
4. Keep the application small, modular, and in-memory for local use and interview review.
5. Improve broad outage-style query handling with a deterministic query rewrite layer rather than a large rule engine or reranker.

## Implemented Interfaces

### `GET /v2/search?q=...`

Purpose:
Run Phase 2 semantic retrieval and return ranked SOP results.

Response shape:

```json
{
  "query": "服务器挂了",
  "results": [
    {
      "id": "sop-001",
      "title": "后端服务 On-Call SOP",
      "snippet": "...",
      "score": 0.7421
    }
  ]
}
```

Behavior notes:

- The response shape intentionally matches the Phase 1 search contract: `query` plus a list of `id`, `title`, `snippet`, and `score`.
- The returned `score` is a display-oriented confidence score that stays monotonic with the ranked order. Internally, Phase 2 still uses hybrid rank fusion for ordering and then derives a more human-readable confidence value for the API response.
- Blank queries return an empty result list through the same service-layer behavior used elsewhere.
- The Phase 2 search path may rewrite a broad outage-style query into a small set of more specific semantic subqueries before retrieval.
- Returned snippets come from the best semantic chunk for the document, not from the lexical search path.

### `GET /v2`

Purpose:
Serve a minimal semantic search page for local demo and manual validation.

Behavior notes:

- The page is rendered with Jinja2.
- Static JavaScript submits queries to `GET /v2/search` and renders the returned results client-side.
- If a non-blank `q` parameter is present on initial page load, the server renders initial semantic results.

## Architecture Overview

The Phase 2 implementation is layered on top of the existing Phase 1 application structure.

### Module Responsibilities

- `app/indexing/chunker.py`
  Parses HTML into section-aware semantic chunks and constructs chunk metadata.

- `app/indexing/semantic_index.py`
  Stores chunk embeddings in memory, loads the sentence-transformer model lazily, and runs cosine-similarity retrieval over normalized embeddings.

- `app/services/semantic_search_service.py`
  Orchestrates semantic ingestion, startup warmup, dense retrieval, optional lexical fusion, deterministic query rewrite, and doc-level result aggregation.

- `app/services/query_rewrite.py`
  Contains the small hand-authored rewrite rules for broad outage-style queries.

- `app/api/v2.py`
  Exposes the Phase 2 API and UI routes.

- `app/main.py`
  Wires Phase 1 and Phase 2 together, loads both indexes at startup, and performs semantic warmup before the app begins serving requests.

- `templates/v2.html` and `static/v2.js`
  Provide the minimal Phase 2 search UI and client-side rendering logic.

### Runtime Flow

The current Phase 2 flow is easiest to think about as two paths.

Ingestion path:

`HTML -> parser/chunker -> chunk embeddings -> semantic index`

Query path:

`query rewrite (when applicable) -> retrieval -> doc aggregation -> API/UI`

In the current code, Phase 2 also reuses the Phase 1 lexical service as a supporting ranking signal for each semantic subquery. There are two separate fusion layers in the current implementation: first, lexical support is fused within each semantic subquery retrieval pass at doc level; second, when query rewriting is triggered, the resulting subquery result sets are merged across query variants with a weighted sum. The result is still a Phase 2 semantic-first retrieval flow, but it does not ignore the lexical baseline that already exists in the application.

## Chunking Strategy

Phase 2 does not embed whole documents.

Instead, `app/indexing/chunker.py` produces section-aware chunks from the HTML structure:

- `h2` and `h3` headings define section boundaries
- visible `p` and `li` content under those headings is grouped together
- `script`, `style`, and `noscript` content is excluded because the chunker reuses the same visible-text policy as Phase 1
- simple hidden content is skipped using the same `hidden`, `aria-hidden`, `display:none`, and `visibility:hidden` checks already used in the HTML parsing path

Each chunk stores:

- `chunk_id`
- `doc_id`
- `title`
- `section_path`
- `text`
- `search_text`

`search_text` is built from `title + section_path + text`, then normalized. That gives the embedding model both the local content and a small amount of structural context.

Chunk-level retrieval was chosen because the SOPs contain multiple operational sections per document. Whole-document embeddings would blur together unrelated scenarios, escalation rules, and tool references into a single vector. Chunking keeps the retrieval unit closer to the actual incident scenario text that the query is trying to match.

## Semantic Retrieval Design

Phase 2 uses a small in-memory dense retrieval stack.

### Embeddings

- The preferred model is `paraphrase-multilingual-mpnet-base-v2`
- The fallback model is `paraphrase-multilingual-MiniLM-L12-v2`
- The model is loaded through `sentence-transformers`
- Embeddings are normalized before search

### Index

`app/indexing/semantic_index.py` stores:

- chunk metadata
- chunk embeddings
- a doc-to-chunk mapping
- a dense embedding matrix used for search

Query search is cosine similarity implemented as a dot product over normalized vectors.

### Doc Aggregation

Semantic search initially ranks chunks, not documents. `SemanticSearchService` then aggregates chunk hits to doc-level results by keeping the highest-scoring chunk per document. The best chunk also provides the document snippet.

### Supporting Lexical Signal

The current Phase 2 runtime also consults the existing Phase 1 lexical service for each semantic subquery. That lexical signal is fused at doc level using a small rank-based weighting scheme, so the dense semantic path remains primary while the lexical baseline adds some stability for broad operational wording.

This is still a lightweight retrieval layer, not a full production search engine. The implementation is intentionally readable and in-memory.

## Startup Warmup Behavior

Phase 2 warms the semantic index during application startup.

In `app/main.py`:

1. Phase 1 documents are loaded into the lexical index.
2. The same corpus is loaded into the semantic service.
3. `semantic_service.warmup()` is called before the app starts serving requests.

This ensures the initial SOP corpus is chunked, embedded, and indexed during startup rather than on the first live `/v2/search` request. The warmup behavior is covered by a deterministic test in `tests/test_v2_startup.py`.

## Query Rewrite / Expansion Layer

Phase 2 now includes a very small deterministic query rewrite helper in `app/services/query_rewrite.py`.

Current behavior:

- The original user query is always retained.
- Rewriting only applies to broad outage-style queries.
- No LLM is used.
- The rewrite set is hand-authored and intentionally small.

The current broad outage rewrite example is:

- `服务器挂了`
- `后端服务挂了`
- `SRE 集群故障`
- `服务不可用`

The trigger logic is also intentionally narrow. It looks for a broad entity marker such as `服务器`, `服务`, or `系统` together with an outage marker such as `挂了`, `不可用`, `故障`, or `宕机`, while avoiding expansion when the query already contains more specific domain markers like `后端`, `SRE`, `集群`, `节点`, `网关`, `负载均衡`, `安全`, or `模型`.

This layer was added because the diagnostic work showed that broad outage queries were underspecified relative to the responsibility-domain language in the SOP corpus. The rewrite helper improves task-aligned retrieval without replacing the core semantic stack.

## Query Variant Score Merging

When query rewriting is triggered, Phase 2 runs multiple semantic searches:

1. the original query
2. a small number of rewritten queries

For each subquery, the service runs the normal Phase 2 retrieval path, including semantic retrieval and the current lexical-support fusion for that subquery.

The final result then merges evidence across those subqueries.

The current merge behavior is a weighted sum over per-subquery result scores:

- for the common 4-query broad-outage case, the weights are:
  - original query: `0.40`
  - backend-oriented rewrite: `0.30`
  - SRE-oriented rewrite: `0.25`
  - generic availability rewrite: `0.05`

This keeps the original query relevant, but lets the two main disambiguating rewrites contribute more combined influence than the broad query alone. The merge still preserves score differentiation, so top results do not collapse to identical `1.0000` values as easily as they did under the earlier max-style variant merge.

## Validation Cases

The important Phase 2 target queries are:

- `服务器挂了`
  Validates broad outage handling across backend and infrastructure responsibility domains.

- `黑客攻击`
  Validates that sharper security-oriented semantic queries still surface the information-security SOP without needing broad query expansion.

- `机器学习模型出问题`
  Validates semantic retrieval against the AI/model-operations SOP when the user’s wording is task-oriented rather than copied from the document text.

These behaviors are covered by the current Phase 2 test suite and the manual smoke script.

## Diagnostic Findings

The Phase 2 diagnostic work led to three practical conclusions:

1. The `服务器挂了` failure mode was not treated as a pure model failure.
2. Query underspecification was a major factor.
3. Chunking also influenced the ranking.

That combination is why the current implementation adds a small deterministic query rewrite layer instead of replacing the embedding model or adding a reranker immediately.

The repository also includes `scripts/diagnose_v2.py`, which was added to make those comparisons reproducible by varying query wording, chunk granularity, and raw top-chunk inspection under the same semantic model.

## Smoke Script / Manual Verification

Phase 2 includes a developer-facing smoke script:

`scripts/smoke_v2.py`

It:

- loads the real lexical and semantic services
- warms the semantic index
- runs the core Phase 2 validation queries
- prints top result IDs, titles, scores, and snippets
- shows expanded queries when the deterministic rewrite layer is triggered

Run it with:

```bash
python scripts/smoke_v2.py
```

Optional flags:

- `--data-dir`
- `--top-k`
- `--queries`

This script is for manual verification only. It is not a benchmark and not part of pytest.

## How to Run Phase 2

```bash
uvicorn app.main:app --reload
pytest
python scripts/smoke_v2.py
python scripts/diagnose_v2.py
```

## Limitations of Phase 2

Phase 2 is intentionally limited.

Current limitations include:

- The system is still fully in memory.
- There is no persistence layer and no distributed indexing.
- The retrieval stack is not designed as a production-scale search system.
- The deterministic query rewrite layer only covers a narrow class of broad outage queries.
- There is no reranker yet.
- Score values are ranking-oriented signals, not calibrated probabilities.
- Retrieval quality may still depend on how closely the corpus phrasing matches team/domain language in the query.
- Chunking is section-aware, but still heuristic and HTML-structure-dependent.

These limitations are acceptable for this phase because the goal is to establish a testable semantic retrieval baseline first.

## Why Phase 2 Is a Good Baseline for Phase 3

Phase 2 prepares the project for the next stage in three ways:

1. Retrieval is already document-grounded and chunk-aware.
2. The system has clear service boundaries between parsing, indexing, retrieval, and presentation.
3. Both lexical and semantic retrieval paths are now available for later tool-based or agent-driven use.

Phase 3 does not need to replace the retrieval layer. It can build answer generation and reasoning on top of the existing document-grounded retrieval interfaces.

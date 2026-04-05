# Phase 1 Technical Design

## Scope

This document covers Phase 1 only.

Phase 1 is the keyword-based document retrieval stage of the On-Call Assistant. The implemented system ingests HTML SOP documents, extracts visible text, builds an in-memory lexical index, exposes search APIs, and serves a simple search page under the `/v1` route prefix.

## Phase 1 Goals

Phase 1 focuses on five concrete goals:

1. Ingest HTML SOP documents through an API and during local startup.
2. Index visible text only, while excluding non-visible HTML content such as `script`, `style`, and `noscript`.
3. Support keyword search over mixed Chinese, English, and symbol-heavy operational text.
4. Provide both an HTTP API and a minimal web UI for local use.
5. Establish a stable lexical-retrieval baseline that later phases can extend without replacing the whole application structure.

## Implemented Endpoints

### `POST /v1/documents`

Purpose:
Ingest or replace a single HTML document in the in-memory store and lexical index.

Request body:

```json
{
  "id": "sop-001",
  "html": "<html>...</html>"
}
```

Response:

```json
{
  "id": "sop-001",
  "title": "后端服务 On-Call SOP"
}
```

Behavior notes:

- The request schema is validated with Pydantic.
- The document ID is trimmed before ingestion.
- The current implementation treats duplicate document IDs as replacement updates. The old indexed content is removed and the new content becomes searchable under the same ID.
- The endpoint currently returns HTTP `201` both for first-time ingestion and replacement.

### `GET /v1/search?q=...`

Purpose:
Run keyword search against the in-memory lexical index and return ranked results.

Response shape:

```json
{
  "query": "OOM",
  "results": [
    {
      "id": "sop-001",
      "title": "后端服务 On-Call SOP",
      "snippet": "...",
      "score": 1.2345
    }
  ]
}
```

Behavior notes:

- Search responses are serialized with Pydantic models.
- Blank queries currently return HTTP `200` with an empty `results` array.
- Query text is preserved in the response as received by the API, even if the service layer normalizes or strips it for matching.
- Results include `id`, `title`, `snippet`, and `score`.

### `GET /v1`

Purpose:
Serve a minimal search page for local demo and manual verification.

Behavior notes:

- The page is rendered with Jinja2 templates.
- Static CSS and JavaScript are served through FastAPI `StaticFiles`.
- The form is declared as a normal `GET /v1` search form, and the included JavaScript intercepts submission to call `GET /v1/search` and update the result list client-side.
- If a non-blank `q` parameter is present on initial page load, the server renders initial results.

## Architecture Overview

The Phase 1 implementation is intentionally small and modular.

### Module Responsibilities

- `app/core/html_parser.py`
  Parses HTML, removes excluded tags, extracts titles, and returns normalized visible text.

- `app/indexing/tokenizer.py`
  Converts normalized text into searchable tokens for mixed English, Chinese, and selected symbols.

- `app/indexing/lexical_index.py`
  Maintains the in-memory postings structure, document statistics, BM25-style scoring, and snippet generation.

- `app/services/document_service.py`
  Coordinates ingestion and search. This is the main boundary between API handlers and search internals.

- `app/data_store/in_memory_store.py`
  Stores ingested document metadata and visible text in memory.

- `app/api/v1.py`
  Defines the Phase 1 HTTP endpoints and maps service-layer results into response schemas.

- `templates/v1.html`, `static/app.css`, `static/v1.js`
  Provide the minimal search UI and client-side fetch behavior for `/v1`.

### Request and Data Flow

The Phase 1 data path is:

`HTML -> parser -> tokenizer -> lexical index -> search results -> API/UI`

More concretely:

1. A document is ingested through `POST /v1/documents` or loaded from the configured data directory during application startup. In the default application setup, that directory is `./data` under the Phase 1 project root.
2. `DocumentService` calls the HTML parser to extract the document title and visible text.
3. The visible text is stored in the in-memory document store.
4. The same visible text is tokenized and indexed into the lexical index.
5. Search queries are tokenized using the same tokenizer.
6. The lexical index scores candidate documents and builds snippets.
7. The API returns structured results, or the UI renders them.

## HTML Parsing Strategy

Phase 1 uses `BeautifulSoup` with the `html5lib` parser. This choice is practical for the supplied SOP corpus because the HTML files are human-authored and may contain entities, inconsistent structure, or malformed markup.

The implemented parsing behavior is:

- Remove all `script`, `style`, and `noscript` tags before text extraction.
- Extract the title in this order:
  1. `<title>`
  2. first visible `<h1>`
  3. document ID fallback
- Extract visible text from the document body when available.
- If `<body>` is missing, fall back to the `<html>` element or document root, while still treating `<head>` as non-visible.
- Skip text under non-visible containers and simple hidden elements.
- Normalize HTML entities and whitespace.
- Apply Unicode NFKC normalization before final text normalization.

The current hidden-content heuristic excludes content when an element:

- has the `hidden` attribute
- has `aria-hidden="true"`
- has inline `display:none`
- has inline `visibility:hidden`

This parser is intentionally heuristic rather than a full browser rendering model. For Phase 1, that tradeoff is appropriate because the main requirement is to reliably index visible SOP text while excluding obvious non-visible content. The test suite also locks down malformed HTML handling so script and head-only text do not leak into the searchable body text.

## Tokenization Strategy

The tokenizer is designed for the SOP corpus rather than for general multilingual linguistic analysis.

Current behavior:

- ASCII alphanumeric terms are case-folded.
- Unicode NFKC normalization is applied on the query/tokenization path, so full-width query forms normalize consistently with document text.
- Common technical tokens with internal separators are preserved as a single token when the separator appears between ASCII term characters. Examples:
  - `read-only`
  - `redis-cluster`
  - `error_code`
  - `api/v1`
- Chinese text is tokenized as overlapping bigrams.
- `&` is preserved as a searchable symbol token.
- Separator characters by themselves do not become standalone noisy tokens.

This mixed strategy is more appropriate than naive whitespace splitting for this dataset because the SOP corpus contains:

- Chinese text without whitespace-delimited words
- uppercase English operational keywords such as `OOM`, `CDN`, and `DNS`
- technical identifiers with punctuation inside the term
- meaningful symbol usage such as `&`

## Ranking and Snippet Generation

Phase 1 uses a simple lexical retrieval pipeline implemented in `app/indexing/lexical_index.py`.

### Ranking

The ranking model is BM25-style and uses:

- per-document term frequencies
- postings lists
- document frequency statistics
- average document length

The implementation keeps a light positional tie-break on top of the BM25 score. Position is not the main ranking signal; it is only used to slightly prefer documents where the first match appears earlier in the visible text.

This is intentionally modest. It is enough to produce reasonable ordering on the supplied SOP corpus without introducing heavier search infrastructure.

### Snippet Generation

Snippets are generated from the stored visible text:

- Prefer a window around the first matched token.
- Fall back to the beginning of the document text when no match position is available.
- Trim at simple text boundaries where possible.
- Add leading or trailing ellipses when the snippet is a middle slice of the document.

The current implementation does not do query-term highlighting or section-aware summarization.

## Edge Cases and Hardening

The Phase 1 test suite locks down several behaviors that are easy to regress:

- Empty or bodyless HTML ingestion is safe.
  Documents such as `""`, `<html></html>`, and `<body></body>` ingest without crashing, fall back to the document ID as title, and store empty visible text.

- Duplicate document IDs follow replacement semantics.
  Re-ingesting the same ID replaces the previously indexed content, and the old content is no longer searchable.

- Blank queries return empty results consistently.
  The service layer returns an empty list, and the API returns HTTP `200` with an empty `results` array.

- Malformed HTML does not leak script or head-only content into searchable visible text.

- Full-width query forms normalize correctly.
  This includes query-side normalization for terms such as `ＡＰＩ／v1` and `＆`.

## Validation Cases

The current implementation and tests cover the core validation targets used to assess Phase 1 behavior:

- `OOM`
  Confirms uppercase English operational keywords remain searchable and that the backend SOP appears in the top results.

- `故障`
  Confirms Chinese keyword matching across multiple SOP documents.

- `replication`
  Confirms text that appears only inside `script` tags is not indexed.

- `CDN`
  Confirms English technical keywords match the expected front-end and network SOPs.

- `&`
  Confirms visible symbol tokens remain searchable.

- `ＡＰＩ／v1`
  Confirms full-width query forms normalize consistently with document-side normalization. The test covers this by ingesting a document containing `API/v1` and querying it with the full-width form.

- `＆`
  Confirms full-width symbol queries normalize to the same searchable token as `&`.

Together, these cases exercise the parser, tokenizer, index, and API contract rather than only simple substring matching.

## How to Run Phase 1

Start the app:

```bash
uvicorn app.main:app --reload
```

Run tests:

```bash
pytest
```

Run the benchmark:

```bash
python scripts/benchmark_v1.py
```

## Benchmark

Phase 1 includes a lightweight benchmark script at:

`scripts/benchmark_v1.py`

The script reuses the existing `DocumentService` rather than implementing separate benchmark-only logic.

It measures:

1. Indexing time for the HTML files under `./data`
2. Average search latency over repeated runs
3. P95 search latency
4. Per-query timing for representative queries
5. Result counts for basic sanity checking

Default representative queries are:

- `OOM`
- `故障`
- `CDN`
- `ＡＰＩ／v1`
- `&`

Example command:

```bash
python scripts/benchmark_v1.py
```

Optional arguments:

- `--runs`
- `--data-dir`
- `--queries`

This benchmark is intended to provide a simple local baseline for later phases. It does not attempt to simulate concurrent traffic or large-scale production load.

## Limitations of Phase 1

Phase 1 is intentionally limited to lexical retrieval.

Current limitations include:

- No semantic matching yet. Queries must still overlap lexically with indexed content.
- In-memory storage only. There is no persistence across process restarts.
- No external search engine or distributed indexing.
- Ranking is a small BM25-style implementation tuned for a compact SOP corpus, not a large production search system.
- No chunk-level retrieval yet. Documents are indexed at the whole-document level.
- No advanced multilingual morphological analysis beyond ASCII token handling and CJK bigrams.
- No query expansion, synonym handling, or fuzzy matching.
- No advanced result highlighting beyond simple snippet extraction.

These limits are acceptable for Phase 1 because the goal is to build a clear and testable lexical baseline first.

## Why Phase 1 Is a Good Baseline for Phase 2

Even though Phase 1 is lexical only, its structure is useful for later work.

The current design already separates:

- document parsing
- tokenization and indexing
- storage
- service orchestration
- API presentation

That separation makes it easier to extend the system toward:

- chunk-level semantic retrieval
- hybrid lexical plus semantic ranking
- later agent or tool-based reasoning that still depends on reliable document ingestion and retrieval boundaries

Phase 2 does not need to replace the Phase 1 structure. It can build on the same ingestion path and service boundaries while introducing semantic retrieval alongside the current lexical baseline.

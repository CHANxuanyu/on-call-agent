# Phase 3 Technical Design

## Scope

This document covers Phase 3 only.

Phase 3 adds a constrained dialogue / agent-style layer on top of the earlier project stages. It does not replace Phase 1 or Phase 2, and it is not implemented as a general autonomous agent. Instead, Phase 3 provides a small chat workflow that routes through a generated catalog, reads specific SOP files through a single safe tool boundary, and answers with references to the files it actually consulted.

## Phase 3 Goals

Phase 3 focuses on seven concrete goals:

1. Add a chat-style interface over the SOP corpus.
2. Keep document access constrained to a single tool: `readFile(fname)`.
3. Ground answers in files actually read through that tool.
4. Use a generated catalog as the routing index for file selection.
5. Keep session continuity in memory only.
6. Return visible tool traces for transparency.
7. Respond conservatively when catalog-based routing confidence is weak.

## Implemented Interfaces

### `GET /v3`

Purpose:
Serve the Phase 3 chat page.

Behavior notes:

- The page is rendered with Jinja2.
- It provides a message composer, an `X-API-Key` input, a conversation timeline, a visible tool-trace panel, and a consulted-file list for the latest assistant turn.
- The page restores the current browser-session transcript by calling `GET /v3/history/{session_id}` when a saved session exists.
- The page stores the browser-session `session_id` and the manually entered `X-API-Key` in session storage only.

### `GET /v3/history/{session_id}`

Purpose:
Return the accumulated in-memory conversation turns for one existing Phase 3 session.

Response shape:

```json
{
  "session_id": "existing-session-id",
  "history": [
    {
      "role": "user",
      "content": "数据库主从延迟超过30秒怎么处理？",
      "consulted_files": [],
      "tool_calls": []
    },
    {
      "role": "assistant",
      "content": "...",
      "consulted_files": [
        "sop-002.html"
      ],
      "tool_calls": [
        {
          "tool_name": "readFile",
          "arguments": {
            "fname": "catalog.json"
          },
          "status": "ok",
          "output_preview": "..."
        }
      ]
    }
  ]
}
```

Behavior notes:

- the endpoint returns `404` when the session does not exist
- when `API_KEY` is configured, this endpoint is protected by the same `X-API-Key` requirement as `POST /v3/chat`

### `POST /v3/chat`

Purpose:
Run the Phase 3 dialogue loop for one user message and return the grounded response together with tool-trace data.

Request shape:

```json
{
  "session_id": "optional-session-id",
  "message": "数据库主从延迟超过30秒怎么处理？"
}
```

Response shape:

```json
{
  "session_id": "generated-or-reused-session-id",
  "assistant_message": "...",
  "tool_calls": [
    {
      "tool_name": "readFile",
      "arguments": {
        "fname": "catalog.json"
      },
      "status": "ok",
      "output_preview": "..."
    }
  ],
  "consulted_files": [
    "sop-002.html"
  ],
  "history": [
    {
      "role": "user",
      "content": "数据库主从延迟超过30秒怎么处理？",
      "consulted_files": [],
      "tool_calls": []
    },
    {
      "role": "assistant",
      "content": "...",
      "consulted_files": [
        "sop-002.html"
      ],
      "tool_calls": [
        {
          "tool_name": "readFile",
          "arguments": {
            "fname": "catalog.json"
          },
          "status": "ok",
          "output_preview": "..."
        }
      ]
    }
  ]
}
```

Behavior notes:

- `session_id` is optional on input. If omitted, the service creates one.
- `assistant_message` is the grounded reply produced by the Phase 3 loop.
- `tool_calls` is a structured trace of each tool call, including the file name, status, and a short preview.
- `consulted_files` lists only the SOP files actually read successfully for the current answer.
- `history` returns the current session transcript as user / assistant turns so the chat page can render or restore the conversation timeline.
- `consulted_files` does not include `catalog.json`, failed or rejected SOP reads, or previously consulted files mentioned only for follow-up transparency.
- Request and response validation are handled by Pydantic models in `app/core/schemas.py`.

## Architecture Overview

Phase 3 is implemented as a small layer on top of the existing FastAPI application.

### Module Responsibilities

- `app/agent/tools.py`
  Defines the `readFile(fname)` tool boundary, tool-call record structures, and deterministic catalog generation.

- `app/agent/memory.py`
  Implements the in-memory session store and stores turns, including `consulted_files` and assistant-side `tool_calls`.

- `app/agent/prompting.py`
  Stores the Phase 3 system prompt text. It documents the intended constraints, but the current runtime loop is still deterministic rather than driven by a live LLM planning cycle.

- `app/agent/loop.py`
  Implements the controlled Phase 3 loop: catalog read, catalog scoring, file selection, file reads, grounded answer composition, low-confidence handling, and narrow follow-up behavior.

- `app/services/agent_service.py`
  Owns startup catalog generation, session lookup, and the public `chat(...)` entrypoint used by the API layer.

- `app/api/v3.py`
  Exposes `GET /v3`, `GET /v3/history/{session_id}`, and `POST /v3/chat`.

- `app/main.py`
  Wires the Phase 3 service into the shared FastAPI app and regenerates `catalog.json` during startup.

- `templates/v3.html`
  Provides the Phase 3 chat page shell.

- `static/v3.js`
  Sends chat requests to the API, restores saved sessions through the history endpoint, attaches `X-API-Key` when entered, and renders the timeline plus latest-turn evidence panels.

- `data/catalog.json`
  Provides the generated catalog used as the routing index for Phase 3.

### High-Level Runtime Flow

The current Phase 3 chat path is:

`user message -> session lookup -> read catalog.json -> rank catalog entries -> read top SOP file(s) -> grounded answer -> tool trace returned`

The current page-restore path is:

`saved session_id in browser -> GET /v3/history/{session_id} -> in-memory session lookup -> transcript returned`

There is also a small follow-up shortcut:

- if the user asks which files were consulted previously, the loop still reads `catalog.json` first and then answers from recent session state without reading additional SOP files
- in that follow-up-only path, `consulted_files` stays empty and the answer explicitly marks that it is referring to previously consulted SOP context

## Tool Model and Safety Boundary

Phase 3 exposes a single actual tool boundary:

`readFile(fname)`

Current behavior:

- reads are restricted to the configured data directory
- absolute paths are rejected
- path traversal is rejected
- missing files are rejected
- HTML files are returned as cleaned visible text using the existing HTML parser
- non-HTML files such as `catalog.json` are returned as plain text / JSON text

For HTML files, the returned content is normalized into a simple text form:

- title
- file name
- visible text

This single-tool rule is now respected by the actual Phase 3 routing path, not only by the visible trace. The loop routes by reading `catalog.json` through `readFile`, scoring catalog entries in memory, and then reading only the selected SOP files through the same tool boundary.

## Catalog Strategy

Phase 3 uses a generated `catalog.json` file as its routing index.

Current behavior:

- `catalog.json` is generated deterministically at startup
- it is built automatically from the HTML files under the data directory
- it is not a handwritten route table
- it is used directly for Phase 3 file routing

Each catalog entry currently includes:

- `file_name`
- `doc_id`
- `title`
- `team_or_domain`
- `incident_themes`
- `summary`
- `keywords`
- `scenario_headings`
- `scenario_snippets`
- `operational_terms`
- `escalation_terms`

These fields are derived automatically from the SOP HTML:

- `title` comes from the existing HTML parser
- `team_or_domain` is derived from the title
- `incident_themes` and `scenario_headings` come from `h3` headings
- `scenario_snippets` combine an `h3` heading with nearby paragraph or list text
- `summary` comes from the first usable paragraph, with fallback to visible text
- `keywords` are tokenized from the title, themes, scenario snippets, and summary
- `operational_terms` and `escalation_terms` are matched from the visible text against small built-in operational term lists

This catalog is not a cheat file. It does not contain handwritten mappings for the README example questions. Instead, it provides a stronger automatically generated index that supports generalized routing for related questions.

## Agent Loop Design

The current Phase 3 loop is intentionally small and controlled.

The main steps are:

1. Read `catalog.json` first.
2. Score catalog entries using only catalog-derived information.
3. Choose the top file or files.
4. Read the selected SOP files through `readFile(fname)`.
5. Compose a grounded answer from the consulted file content.
6. Return the answer together with tool traces and consulted file names.

The scoring logic in `app/agent/loop.py` uses only catalog information and small deterministic query normalization. Current scoring signals include:

- overlap with `title` and `team_or_domain`
- overlap with `incident_themes` and `scenario_headings`
- overlap with `scenario_snippets`
- overlap with `keywords`
- overlap with `operational_terms` and `escalation_terms`
- a small bonus for recent consulted files on follow-up-style queries

The loop may read one file or two files depending on the ranking and the query shape. Queries such as `P0 故障的响应流程是什么？` are allowed to consult multiple SOPs when the top catalog signals are close and the query appears to require cross-team response guidance.

This is best described as a constrained agent-style workflow or controlled dialogue layer. It is not a fully autonomous planner and it does not run a general multi-step reasoning loop over arbitrary tools.

## Grounded Answer Composition

Phase 3 prefers content derived from files actually read.

Current answer behavior:

- when a file has been read successfully, the loop extracts grounded detail from that file’s returned content
- candidate segments are built from scenario-style splits, section markers, Chinese-friendly sentence groups, and adjacent sentence pairs
- segments containing boilerplate or introductory text such as scope metadata and generic duty descriptions are down-ranked
- scenario-oriented and operational section content is preferred when it overlaps with the user message
- focused segments that begin at scenario / step / escalation markers are preferred over mixed intro-plus-scenario blobs
- when the user question implies urgency, severity, or threshold crossing, focused conditional escalation segments are preferred over broader remediation-plus-escalation blobs
- when the user question explicitly names an OOM or memory-style symptom, focused symptom segments are preferred over broader same-file backend remediation text
- if no usable grounded segment is found, the loop falls back to catalog-derived support text from `scenario_snippets`, `incident_themes`, or `summary`
- if that still does not yield enough support, it falls back again to the entry summary

For normal grounded answers, the final answer explicitly lists the files consulted for that turn.
For follow-up-only provenance answers, the assistant instead labels the previous-file reference explicitly while keeping current-turn `consulted_files` empty.

This makes the Phase 3 reply more grounded than a simple retrieval wrapper. The routing decision comes from the catalog, but the answer content is intended to come primarily from files that were actually opened through `readFile(fname)`.

## Minimal Session Memory

Phase 3 keeps session state in memory only.

Current behavior:

- sessions are keyed by `session_id`
- turns are stored in an `InMemorySessionStore`
- assistant turns retain `consulted_files` and latest-turn `tool_calls`
- no persistence layer is used

This is not a full long-context memory system. It is a small session mechanism that preserves enough state for limited dialogue continuity.

## Minimal Follow-Up Behavior

Phase 3 includes a narrow follow-up mechanism.

Current behavior:

- if the user asks a follow-up such as `你刚才看了哪些文件？`, the loop can answer from recent session state
- the loop still reads `catalog.json` first on that turn before producing the follow-up answer
- recent assistant turns are scanned for the last consulted file list
- if no SOP is reopened on the current turn, `consulted_files` stays empty because it only reflects files actually read on that turn
- the follow-up answer wording explicitly marks that those file names come from previously consulted SOP context, currently via `上次参考 SOP`
- recent consulted files may also slightly influence routing when the new message looks like a follow-up query

This logic is intentionally limited:

- it only looks at a small recent window
- it only retains consulted file names, not a large conversational summary
- it does not attempt general conversation planning

## Validation Cases

The Phase 3 tests lock down the main README-aligned behaviors of the dialogue layer:

- `数据库主从延迟超过30秒怎么处理？`
  Routes to `sop-002.html` and returns grounded replication-delay handling content.

- `服务 OOM 了怎么办？`
  Routes to `sop-001.html` and returns grounded backend handling guidance.

- `P0 故障的响应流程是什么？`
  Reads multiple SOPs and synthesizes a broader response path.

- `怀疑有人入侵了系统`
  Routes to `sop-005.html` and returns grounded security response content.

- `推荐结果质量下降了`
  Routes to `sop-008.html` and returns grounded AI / recommendation troubleshooting content.

These behaviors are not implemented through a handwritten question-to-file map. They emerge from the generated catalog fields and the deterministic catalog-scoring logic.

The tests also cover:

- catalog-first tool order
- path traversal rejection
- follow-up file-question behavior
- consulted-file truthfulness for the current turn, including keeping failed SOP reads out of `consulted_files`
- grounding that prefers scenario content over generic intro text
- grounding that prefers focused remediation-flow content over mixed intro-plus-remediation blobs
- grounding that prefers explicit threshold-triggered escalation guidance over nearby generic remediation prose when the query asks about escalation
- grounding that prefers OOM / memory symptom guidance over nearby generic backend remediation prose when the query asks about that symptom
- a related unseen query such as `从库复制卡住了，先看什么？`
- conservative handling for weak or ambiguous routing signals

## Low-Confidence Behavior

Phase 3 now has an explicit low-confidence path.

Current behavior:

- if catalog routing is weak or ambiguous, the loop responds conservatively
- it avoids pretending certainty
- it may stop after reading only `catalog.json`
- it asks the user to clarify the issue domain rather than reading random unrelated files

This behavior is deliberate. It keeps the assistant grounded and makes the limits of the current routing logic visible instead of masking them with overconfident guesses.

## UI Behavior

The `GET /v3` page provides a minimal chat interface with:

- a chat composer
- an `X-API-Key` input for the app service key
- a visible conversation timeline
- a visible tool trace for the latest assistant turn
- a consulted-file list for the latest assistant turn
- a new-chat reset action

The current client-side rendering formats assistant answers into separate sections, keeps tool usage visible in compact trace cards, and displays consulted files separately for the latest assistant turn. The JavaScript client posts messages to `POST /v3/chat`, keeps the returned `session_id`, restores prior turns through `GET /v3/history/{session_id}`, and sends `X-API-Key` when the user provides it in the page input.

## How to Run Phase 3

```bash
uvicorn app.main:app --reload
pytest
```

Open `/v3` in the browser for manual validation.

## Limitations of Phase 3

Phase 3 is intentionally limited.

Current limitations include:

- the loop is constrained and mostly deterministic
- this is not a general-purpose autonomous agent
- there is no persistent memory
- there is no multi-tool planning system
- there is no live LLM-based planning or reasoning loop in the current runtime path
- routing quality depends on the quality of the generated catalog and the heuristic scoring signals
- generalized routing is still heuristic rather than learned
- only a single safe file-reading tool is exposed
- the catalog is generated at startup, but the current Phase 3 code does not independently refresh it after later document ingestion events unless startup or explicit regeneration occurs again

These constraints are deliberate. They keep the final layer small, inspectable, and testable.

## Why Phase 3 Is a Reasonable Final Layer for This Project

Phase 3 is a reasonable final layer for this project because it adds dialogue and explicit tool use without rewriting the earlier phases.

It remains grounded in file reads, keeps routing and tool usage inspectable, respects the README single-tool requirement more directly after the routing refactor, and stays small enough to explain and test clearly in an interview setting.

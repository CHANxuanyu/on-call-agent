from __future__ import annotations

import argparse
from pathlib import Path
import sys
from time import perf_counter


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_QUERIES = ("服务器挂了", "黑客攻击", "机器学习模型出问题")
SNIPPET_MAX_CHARS = 160

sys.path.insert(0, str(PROJECT_ROOT))

from app.data_store.in_memory_store import InMemoryDocumentStore
from app.indexing.lexical_index import BM25LexicalIndex
from app.indexing.tokenizer import Tokenizer
from app.services.document_service import DocumentService
from app.services.query_rewrite import expand_semantic_query
from app.services.semantic_search_service import SemanticSearchService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manual smoke test for Phase 2 semantic search.")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Directory containing SOP HTML files. Default: ./data",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=3,
        help="Number of semantic search results to print per query. Default: 3",
    )
    parser.add_argument(
        "--queries",
        nargs="*",
        default=list(DEFAULT_QUERIES),
        help="Semantic queries to run. Default: core Phase 2 validation queries.",
    )
    return parser.parse_args()


def shorten(text: str, *, limit: int = SNIPPET_MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def main() -> None:
    args = parse_args()
    data_dir = args.data_dir.resolve()

    if args.top_k <= 0:
        raise SystemExit("--top-k must be a positive integer")
    if not data_dir.exists():
        raise SystemExit(f"data directory not found: {data_dir}")

    lexical_service = DocumentService(
        store=InMemoryDocumentStore(),
        index=BM25LexicalIndex(tokenizer=Tokenizer()),
    )
    service = SemanticSearchService(lexical_service=lexical_service)

    load_started_at = perf_counter()
    lexical_service.load_documents_from_directory(data_dir)
    indexed_count = service.load_documents_from_directory(data_dir)
    load_ms = (perf_counter() - load_started_at) * 1000

    warmup_started_at = perf_counter()
    try:
        service.warmup()
    except Exception as exc:
        raise SystemExit(
            "Failed to load the Phase 2 semantic model or build the semantic index.\n"
            "Install project dependencies with `pip install -r requirements.txt`, then ensure the "
            "sentence-transformer model can be downloaded or is already cached locally.\n"
            f"Original error: {exc}"
        ) from exc
    warmup_ms = (perf_counter() - warmup_started_at) * 1000

    embedder = getattr(getattr(service, "_index", None), "_embedder", None)
    model_name = getattr(embedder, "model_name", None)

    print(f"loaded {indexed_count} docs in {load_ms:.2f} ms")
    print(f"built semantic index in {warmup_ms:.2f} ms")
    if model_name:
        print(f"embedding model: {model_name}")

    for query in args.queries:
        print()
        print(f"=== Query: {query} ===")
        expanded_queries = expand_semantic_query(query)
        if len(expanded_queries) > 1:
            print(f"expanded queries: {', '.join(expanded_queries)}")
        search_started_at = perf_counter()
        hits = service.search(query, limit=args.top_k)
        search_ms = (perf_counter() - search_started_at) * 1000

        if not hits:
            print(f"no results (search time {search_ms:.2f} ms)")
            continue

        for index, hit in enumerate(hits, start=1):
            print(f"{index}. {hit.id} | {hit.title} | score={hit.score:.4f}")
            print(f"   snippet: {shorten(hit.snippet)}")
        print(f"search time: {search_ms:.2f} ms")


if __name__ == "__main__":
    main()

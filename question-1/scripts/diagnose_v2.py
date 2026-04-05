from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys
from time import perf_counter
from typing import Protocol, Sequence

from bs4 import BeautifulSoup


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_QUERIES = (
    "服务器挂了",
    "后端服务挂了",
    "SRE 集群故障",
    "节点挂了",
    "服务不可用",
    "网关挂了",
    "负载均衡异常",
    "后端实例不可用",
)
DOCS_OF_INTEREST = ("sop-001", "sop-004", "sop-010")
RAW_CHUNK_LIMIT = 20

sys.path.insert(0, str(PROJECT_ROOT))

from app.core.html_parser import REMOVED_TAGS, parse_html_document
from app.indexing.chunker import (
    CONTENT_TAGS,
    SECTION_HEADINGS,
    HtmlSectionChunker,
    SemanticChunk,
    _build_search_text,
    _has_non_visible_ancestor,
    _normalize_text,
    _update_section_path,
)
from app.indexing.semantic_index import ChunkSearchHit, InMemorySemanticIndex, SentenceTransformerEmbedder


class Chunker(Protocol):
    def chunk_document(self, document_id: str, html: str, *, title: str | None = None) -> list[SemanticChunk]: ...


@dataclass(slots=True)
class DiagnosticDocHit:
    doc_id: str
    title: str
    score: float
    section_path: str
    chunk_text: str


@dataclass(slots=True)
class ModeArtifacts:
    name: str
    chunker: Chunker
    index: InMemorySemanticIndex
    chunk_count: int
    build_ms: float


class FineParagraphChunker:
    """One semantic chunk per visible paragraph/list item under the current heading path."""

    def chunk_document(self, document_id: str, html: str, *, title: str | None = None) -> list[SemanticChunk]:
        parsed = parse_html_document(document_id, html)
        resolved_title = title or parsed.title
        soup, root = _prepare_root(html)

        section_path: list[str] = []
        chunks: list[SemanticChunk] = []

        for element in root.find_all(list(SECTION_HEADINGS) + list(CONTENT_TAGS), recursive=True):
            if _has_non_visible_ancestor(element):
                continue

            text = _normalize_text(element.get_text(" ", strip=True))
            if not text:
                continue

            if element.name in SECTION_HEADINGS:
                section_path = _update_section_path(section_path, SECTION_HEADINGS[element.name], text)
                continue

            chunk_number = len(chunks) + 1
            section_path_text = " > ".join(section_path)
            chunks.append(
                SemanticChunk(
                    chunk_id=f"{document_id}::chunk-{chunk_number:03d}",
                    doc_id=document_id,
                    title=resolved_title,
                    section_path=section_path_text,
                    text=text,
                    search_text=_build_search_text(resolved_title, section_path_text, text),
                )
            )

        return chunks or _fallback_chunks(document_id, resolved_title, parsed.visible_text)


class CoarseH2Chunker:
    """One semantic chunk per h2 section, folding h3 sub-sections into the parent h2 chunk."""

    def chunk_document(self, document_id: str, html: str, *, title: str | None = None) -> list[SemanticChunk]:
        parsed = parse_html_document(document_id, html)
        resolved_title = title or parsed.title
        soup, root = _prepare_root(html)

        current_h2 = ""
        text_buffer: list[str] = []
        chunks: list[SemanticChunk] = []

        for element in root.find_all(["h2", "h3", *CONTENT_TAGS], recursive=True):
            if _has_non_visible_ancestor(element):
                continue

            text = _normalize_text(element.get_text(" ", strip=True))
            if not text:
                continue

            if element.name == "h2":
                _flush_coarse_chunk(
                    chunks=chunks,
                    doc_id=document_id,
                    title=resolved_title,
                    section_path=current_h2,
                    text_buffer=text_buffer,
                )
                current_h2 = text
                continue

            if element.name == "h3":
                text_buffer.append(text)
                continue

            text_buffer.append(text)

        _flush_coarse_chunk(
            chunks=chunks,
            doc_id=document_id,
            title=resolved_title,
            section_path=current_h2,
            text_buffer=text_buffer,
        )

        return chunks or _fallback_chunks(document_id, resolved_title, parsed.visible_text)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 2 semantic retrieval diagnostic workflow.")
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
        help="Number of document results to print per query. Default: 3",
    )
    parser.add_argument(
        "--queries",
        nargs="*",
        default=list(DEFAULT_QUERIES),
        help="Query variants to use for the query-sensitivity section.",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=180,
        help="Maximum characters to show for chunk text. Default: 180",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_dir = args.data_dir.resolve()

    if args.top_k <= 0:
        raise SystemExit("--top-k must be a positive integer")
    if args.max_chars <= 0:
        raise SystemExit("--max-chars must be a positive integer")
    if not args.queries:
        raise SystemExit("--queries must contain at least one query")
    if not data_dir.exists():
        raise SystemExit(f"data directory not found: {data_dir}")

    embedder = SentenceTransformerEmbedder()
    modes = build_modes(data_dir, embedder)

    print("=== Phase 2 dense retrieval diagnosis ===")
    print(f"data_dir: {data_dir}")
    if getattr(embedder, "model_name", None):
        print(f"embedding model: {embedder.model_name}")
    print()

    print("=== Query sensitivity ===")
    print("Current production chunking with the current semantic model.")
    for query in args.queries:
        doc_hits, _ = search_mode(modes["baseline"], query, top_k=args.top_k)
        print()
        print(f"--- Query: {query} ---")
        print_doc_hits(doc_hits, max_chars=args.max_chars)

    print()
    print("=== Chunking ablation ===")
    print('Same semantic model, same query: "服务器挂了"')
    for mode_name in ("baseline", "fine", "coarse"):
        mode = modes[mode_name]
        doc_hits, _ = search_mode(mode, "服务器挂了", top_k=args.top_k)
        print()
        print(f"--- Mode: {mode.name} ---")
        print(f"chunks={mode.chunk_count} build_time={mode.build_ms:.2f} ms")
        print_doc_hits(doc_hits, max_chars=args.max_chars)

    print()
    print("=== Top chunk inspection ===")
    print('Current production chunking, raw top chunk hits for query: "服务器挂了"')
    _, raw_hits = search_mode(modes["baseline"], "服务器挂了", top_k=args.top_k)
    print_chunk_hits(raw_hits[:5], max_chars=args.max_chars)
    print()
    print("--- Best matching chunks for key documents ---")
    print_key_document_chunks(raw_hits, max_chars=args.max_chars)

    print()
    print("=== Summary ===")
    print_summary(modes, queries=args.queries, top_k=args.top_k)


def build_modes(data_dir: Path, embedder: SentenceTransformerEmbedder) -> dict[str, ModeArtifacts]:
    definitions: list[tuple[str, str, Chunker]] = [
        ("baseline", "Baseline / current production chunking", HtmlSectionChunker()),
        ("fine", "Fine / per-paragraph chunking", FineParagraphChunker()),
        ("coarse", "Coarse / per-h2 chunking", CoarseH2Chunker()),
    ]

    artifacts: dict[str, ModeArtifacts] = {}
    for key, label, chunker in definitions:
        build_started_at = perf_counter()
        index = InMemorySemanticIndex(embedder=embedder)
        chunk_count = 0

        for path in sorted(data_dir.glob("*.html")):
            html = path.read_text(encoding="utf-8")
            chunks = chunker.chunk_document(path.stem, html)
            index.index_chunks(chunks)
            chunk_count += len(chunks)

        build_ms = (perf_counter() - build_started_at) * 1000
        artifacts[key] = ModeArtifacts(
            name=label,
            chunker=chunker,
            index=index,
            chunk_count=chunk_count,
            build_ms=build_ms,
        )

    return artifacts


def search_mode(mode: ModeArtifacts, query: str, *, top_k: int) -> tuple[list[DiagnosticDocHit], list[ChunkSearchHit]]:
    raw_hits = mode.index.search(query, limit=max(top_k * 5, RAW_CHUNK_LIMIT))
    return aggregate_doc_hits(raw_hits, limit=top_k), raw_hits


def aggregate_doc_hits(chunk_hits: Sequence[ChunkSearchHit], *, limit: int) -> list[DiagnosticDocHit]:
    best_hit_by_doc: dict[str, ChunkSearchHit] = {}

    for hit in chunk_hits:
        current_best = best_hit_by_doc.get(hit.chunk.doc_id)
        if current_best is None or hit.score > current_best.score:
            best_hit_by_doc[hit.chunk.doc_id] = hit

    doc_hits = [
        DiagnosticDocHit(
            doc_id=hit.chunk.doc_id,
            title=hit.chunk.title,
            score=hit.score,
            section_path=hit.chunk.section_path,
            chunk_text=hit.chunk.text,
        )
        for hit in best_hit_by_doc.values()
    ]
    doc_hits.sort(key=lambda hit: (-hit.score, hit.doc_id))
    return doc_hits[:limit]


def print_doc_hits(doc_hits: Sequence[DiagnosticDocHit], *, max_chars: int) -> None:
    if not doc_hits:
        print("no document hits")
        return

    for index, hit in enumerate(doc_hits, start=1):
        print(f"{index}. {hit.doc_id} | {hit.title} | score={hit.score:.4f}")
        if hit.section_path:
            print(f"   section: {hit.section_path}")
        print(f"   best chunk: {shorten(hit.chunk_text, max_chars=max_chars)}")


def print_chunk_hits(chunk_hits: Sequence[ChunkSearchHit], *, max_chars: int) -> None:
    if not chunk_hits:
        print("no chunk hits")
        return

    for index, hit in enumerate(chunk_hits, start=1):
        section_path = hit.chunk.section_path or "(root)"
        print(f"{index}. {hit.chunk.doc_id} | {section_path} | score={hit.score:.4f}")
        print(f"   chunk: {shorten(hit.chunk.text, max_chars=max_chars)}")


def print_key_document_chunks(chunk_hits: Sequence[ChunkSearchHit], *, max_chars: int) -> None:
    best_by_doc: dict[str, ChunkSearchHit] = {}
    for hit in chunk_hits:
        current_best = best_by_doc.get(hit.chunk.doc_id)
        if current_best is None or hit.score > current_best.score:
            best_by_doc[hit.chunk.doc_id] = hit

    for doc_id in DOCS_OF_INTEREST:
        hit = best_by_doc.get(doc_id)
        if hit is None:
            print(f"{doc_id}: no chunk in the inspected result window")
            continue
        section_path = hit.chunk.section_path or "(root)"
        print(f"{doc_id} | {hit.chunk.title} | {section_path} | score={hit.score:.4f}")
        print(f"   chunk: {shorten(hit.chunk.text, max_chars=max_chars)}")


def print_summary(modes: dict[str, ModeArtifacts], *, queries: Sequence[str], top_k: int) -> None:
    baseline_ranks_by_query = {
        query: doc_rank_map(search_mode(modes["baseline"], query, top_k=top_k)[0])
        for query in queries
    }
    baseline_query = queries[0]
    baseline_ranks = baseline_ranks_by_query[baseline_query]

    query_shift_count = 0
    for query in queries[1:]:
        ranks = baseline_ranks_by_query[query]
        if _is_better_rank(ranks.get("sop-001"), baseline_ranks.get("sop-001")) or _is_better_rank(
            ranks.get("sop-004"), baseline_ranks.get("sop-004")
        ):
            query_shift_count += 1

    ablation_ranks = {
        mode_name: doc_rank_map(search_mode(mode, baseline_query, top_k=top_k)[0])
        for mode_name, mode in modes.items()
    }
    chunking_shift = any(
        _rank_distance(ablation_ranks["baseline"].get(doc_id), ranks.get(doc_id)) >= 2
        for mode_name, ranks in ablation_ranks.items()
        if mode_name != "baseline"
        for doc_id in DOCS_OF_INTEREST
    )
    top1_changes = len({search_mode(mode, baseline_query, top_k=1)[0][0].doc_id for mode in modes.values()}) > 1

    print("Signals pointing to query underspecification:")
    if query_shift_count:
        print(
            f"- {query_shift_count} of {max(len(queries) - 1, 1)} narrower query variants move sop-001 or sop-004 higher than the broad baseline query."
        )
    else:
        print("- The tested query variants do not materially improve sop-001 or sop-004 relative to the broad baseline query.")

    print("Signals pointing to chunking issues:")
    if chunking_shift or top1_changes:
        print("- Changing chunk granularity materially changes the ranks of sop-001, sop-004, or sop-010 for the same query.")
    else:
        print("- Changing chunk granularity does not materially change the key document ranks for the same query.")

    judgment = "both"
    if query_shift_count and not (chunking_shift or top1_changes):
        judgment = "mostly query problem"
    elif (chunking_shift or top1_changes) and not query_shift_count:
        judgment = "mostly chunking problem"
    elif not query_shift_count and not (chunking_shift or top1_changes):
        judgment = "mixed / inconclusive"

    print(f"Best current judgment: {judgment}")
    print("This summary is heuristic and should be read together with the raw chunk outputs above.")


def doc_rank_map(doc_hits: Sequence[DiagnosticDocHit]) -> dict[str, int]:
    return {hit.doc_id: index for index, hit in enumerate(doc_hits, start=1)}


def shorten(text: str, *, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}..."


def _prepare_root(html: str) -> tuple[BeautifulSoup, BeautifulSoup]:
    soup = BeautifulSoup(html, "html5lib")
    for tag_name in REMOVED_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()
    root = soup.body or soup.find("html") or soup
    return soup, root


def _flush_coarse_chunk(
    *,
    chunks: list[SemanticChunk],
    doc_id: str,
    title: str,
    section_path: str,
    text_buffer: list[str],
) -> None:
    text = _normalize_text(" ".join(text_buffer))
    if not text:
        text_buffer.clear()
        return

    chunk_number = len(chunks) + 1
    chunks.append(
        SemanticChunk(
            chunk_id=f"{doc_id}::chunk-{chunk_number:03d}",
            doc_id=doc_id,
            title=title,
            section_path=section_path,
            text=text,
            search_text=_build_search_text(title, section_path, text),
        )
    )
    text_buffer.clear()


def _fallback_chunks(document_id: str, title: str, visible_text: str) -> list[SemanticChunk]:
    if not visible_text:
        return []
    return [
        SemanticChunk(
            chunk_id=f"{document_id}::chunk-001",
            doc_id=document_id,
            title=title,
            section_path="",
            text=visible_text,
            search_text=_build_search_text(title, "", visible_text),
        )
    ]


def _is_better_rank(candidate_rank: int | None, baseline_rank: int | None) -> bool:
    if candidate_rank is None:
        return False
    if baseline_rank is None:
        return True
    return candidate_rank < baseline_rank


def _rank_distance(left: int | None, right: int | None) -> int:
    if left is None and right is None:
        return 0
    if left is None or right is None:
        return 99
    return abs(left - right)


if __name__ == "__main__":
    main()

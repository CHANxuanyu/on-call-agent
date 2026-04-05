from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
from pathlib import Path
import statistics
import sys
from time import perf_counter


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_QUERIES = ("OOM", "故障", "CDN", "ＡＰＩ／v1", "&")

sys.path.insert(0, str(PROJECT_ROOT))

from app.data_store.in_memory_store import InMemoryDocumentStore
from app.indexing.lexical_index import BM25LexicalIndex
from app.indexing.tokenizer import Tokenizer
from app.services.document_service import DocumentService


@dataclass(slots=True)
class QueryBenchmark:
    query: str
    avg_ms: float
    p95_ms: float
    result_count: int
    latencies_ms: list[float]


def build_service() -> DocumentService:
    return DocumentService(
        store=InMemoryDocumentStore(),
        index=BM25LexicalIndex(tokenizer=Tokenizer()),
    )


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0.0

    ordered = sorted(values)
    rank = max(0, math.ceil((percentile_value / 100) * len(ordered)) - 1)
    return ordered[min(rank, len(ordered) - 1)]


def benchmark_query(service: DocumentService, query: str, runs: int) -> QueryBenchmark:
    latencies_ms: list[float] = []
    result_count = 0

    for _ in range(runs):
        started_at = perf_counter()
        result_count = len(service.search(query))
        latencies_ms.append((perf_counter() - started_at) * 1000)

    return QueryBenchmark(
        query=query,
        avg_ms=statistics.fmean(latencies_ms) if latencies_ms else 0.0,
        p95_ms=percentile(latencies_ms, 95),
        result_count=result_count,
        latencies_ms=latencies_ms,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lightweight Phase 1 benchmark for /v1 indexing and search.")
    parser.add_argument("--runs", type=int, default=100, help="Repeated search runs per query. Default: 100")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Directory containing HTML SOP files. Default: ./data",
    )
    parser.add_argument(
        "--queries",
        nargs="*",
        default=list(DEFAULT_QUERIES),
        help="Representative queries to benchmark.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_dir = args.data_dir.resolve()

    if args.runs <= 0:
        raise SystemExit("--runs must be a positive integer")
    if not data_dir.exists():
        raise SystemExit(f"data directory not found: {data_dir}")

    service = build_service()

    indexing_started_at = perf_counter()
    indexed_count = service.load_documents_from_directory(data_dir)
    indexing_ms = (perf_counter() - indexing_started_at) * 1000

    print(f"indexed {indexed_count} docs in {indexing_ms:.3f} ms")

    overall_latencies_ms: list[float] = []
    for query in args.queries:
        benchmark = benchmark_query(service, query, args.runs)
        overall_latencies_ms.extend(benchmark.latencies_ms)
        print(
            f"query={benchmark.query} avg={benchmark.avg_ms:.3f} ms "
            f"p95={benchmark.p95_ms:.3f} ms results={benchmark.result_count}"
        )

    overall_avg_ms = statistics.fmean(overall_latencies_ms) if overall_latencies_ms else 0.0
    overall_p95_ms = percentile(overall_latencies_ms, 95)
    print(
        f"overall avg search latency over {len(overall_latencies_ms)} runs = {overall_avg_ms:.3f} ms "
        f"(p95={overall_p95_ms:.3f} ms)"
    )


if __name__ == "__main__":
    main()

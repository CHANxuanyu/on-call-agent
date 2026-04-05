from __future__ import annotations

from dataclasses import dataclass
import logging
import math
import os
from pathlib import Path
from typing import Any, Callable

from app.indexing.lexical_index import SearchHit
from app.indexing.chunker import HtmlSectionChunker, SemanticChunk
from app.indexing.semantic_index import ChunkSearchHit, InMemorySemanticIndex
from app.services.document_service import DocumentService
from app.services.query_rewrite import expand_semantic_query


SNIPPET_MAX_CHARS = 220
SNIPPET_BOUNDARIES = " \t\r\n。！？；;,.!?:："
FUSION_DENSE_WEIGHT = 0.7
FUSION_LEXICAL_WEIGHT = 0.3
FUSION_CANDIDATE_MULTIPLIER = 3
# Default merge strategy keeps existing weighted query-variant behavior unchanged.
QUERY_VARIANT_MERGE_STRATEGY = "weighted_sum"
# Default temperature keeps display scores unchanged.
DISPLAY_SCORE_TEMPERATURE = 1.0
DISPLAY_SCORE_MIN_STEP = 0.0002
QUERY_VARIANT_WEIGHT_PRESETS = {
    1: (1.0,),
    2: (0.75, 0.25),
    3: (0.6, 0.25, 0.15),
    4: (0.4, 0.3, 0.25, 0.05),
}
DEFAULT_QUERY_VARIANT_WEIGHTS = (0.4, 0.3, 0.25, 0.05)
VALID_QUERY_VARIANT_MERGE_STRATEGIES = frozenset({"weighted_sum", "max_score", "top2_avg"})
V2_SCORE_EXPERIMENT_PRESET_ENV = "V2_SCORE_EXPERIMENT_PRESET"
V2_QUERY_VARIANT_MERGE_STRATEGY_ENV = "V2_QUERY_VARIANT_MERGE_STRATEGY"
V2_DISPLAY_SCORE_TEMPERATURE_ENV = "V2_DISPLAY_SCORE_TEMPERATURE"
V2_FUSION_DENSE_WEIGHT_ENV = "V2_FUSION_DENSE_WEIGHT"
V2_FUSION_LEXICAL_WEIGHT_ENV = "V2_FUSION_LEXICAL_WEIGHT"
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SemanticSearchResult:
    id: str
    title: str
    snippet: str
    score: float


@dataclass(frozen=True, slots=True)
class V2ScoreRuntimeConfig:
    preset_name: str
    query_variant_merge_strategy: str
    fusion_dense_weight: float
    fusion_lexical_weight: float
    display_score_temperature: float


@dataclass(slots=True)
class _ScoredSearchResult:
    raw_score: float
    display_score_basis: float
    result: SemanticSearchResult


V2_SCORE_EXPERIMENT_PRESETS = {
    "baseline": V2ScoreRuntimeConfig(
        preset_name="baseline",
        query_variant_merge_strategy="weighted_sum",
        fusion_dense_weight=0.7,
        fusion_lexical_weight=0.3,
        display_score_temperature=1.0,
    ),
    "separation_soft": V2ScoreRuntimeConfig(
        preset_name="separation_soft",
        query_variant_merge_strategy="top2_avg",
        fusion_dense_weight=0.8,
        fusion_lexical_weight=0.2,
        display_score_temperature=0.9,
    ),
    "separation_strong": V2ScoreRuntimeConfig(
        preset_name="separation_strong",
        query_variant_merge_strategy="max_score",
        fusion_dense_weight=0.85,
        fusion_lexical_weight=0.15,
        display_score_temperature=0.85,
    ),
}
DEFAULT_V2_SCORE_EXPERIMENT_PRESET = "baseline"


class SemanticSearchService:
    def __init__(
        self,
        *,
        chunker: HtmlSectionChunker | None = None,
        index: InMemorySemanticIndex | None = None,
        lexical_service: DocumentService | None = None,
        eager_indexing: bool = False,
        fusion_dense_weight: float | None = None,
        fusion_lexical_weight: float | None = None,
        query_variant_merge_strategy: str | None = None,
        display_score_temperature: float | None = None,
    ) -> None:
        runtime_config = _load_v2_score_runtime_config()
        self._chunker = chunker or HtmlSectionChunker()
        self._index = index or InMemorySemanticIndex()
        self._lexical_service = lexical_service
        self._eager_indexing = eager_indexing
        self._score_experiment_preset = runtime_config.preset_name
        self._fusion_dense_weight = _resolve_numeric_config(
            runtime_config.fusion_dense_weight if fusion_dense_weight is None else fusion_dense_weight,
            default=runtime_config.fusion_dense_weight,
            min_value=0.0,
            max_value=1.0,
        )
        self._fusion_lexical_weight = _resolve_numeric_config(
            runtime_config.fusion_lexical_weight if fusion_lexical_weight is None else fusion_lexical_weight,
            default=runtime_config.fusion_lexical_weight,
            min_value=0.0,
            max_value=1.0,
        )
        self._fusion_dense_weight, self._fusion_lexical_weight = _normalize_fusion_weights(
            dense_weight=self._fusion_dense_weight,
            lexical_weight=self._fusion_lexical_weight,
            default_dense=runtime_config.fusion_dense_weight,
            default_lexical=runtime_config.fusion_lexical_weight,
            context="effective_v2_fusion_weights",
        )
        self._query_variant_merge_strategy = _resolve_query_variant_merge_strategy(
            runtime_config.query_variant_merge_strategy if query_variant_merge_strategy is None else query_variant_merge_strategy,
            default=runtime_config.query_variant_merge_strategy,
        )
        self._display_score_temperature = _resolve_display_score_temperature(
            runtime_config.display_score_temperature if display_score_temperature is None else display_score_temperature,
            default=runtime_config.display_score_temperature,
        )
        self._pending_chunks_by_doc: dict[str, list[SemanticChunk]] = {}
        self._is_shutdown = False

    def set_lexical_service(self, lexical_service: DocumentService | None) -> None:
        self._lexical_service = lexical_service

    def ingest_document(self, document_id: str, html: str) -> list[SemanticChunk]:
        normalized_id = document_id.strip()
        chunks = self._chunker.chunk_document(normalized_id, html)

        self._index.remove_document(normalized_id)
        self._pending_chunks_by_doc[normalized_id] = chunks

        if self._eager_indexing:
            self.flush_pending_chunks()

        return chunks

    def load_documents_from_directory(self, directory: Path) -> int:
        if not directory.exists():
            return 0

        indexed_count = 0
        for path in sorted(directory.glob("*.html")):
            html = path.read_text(encoding="utf-8")
            self.ingest_document(path.stem, html)
            indexed_count += 1

        return indexed_count

    def warmup(self) -> None:
        self.flush_pending_chunks()

    def shutdown(self) -> None:
        if self._is_shutdown:
            return

        self._is_shutdown = True
        self._pending_chunks_by_doc.clear()
        _shutdown_component("semantic_index", self._index)
        _shutdown_component("semantic_chunker", self._chunker)

    def search(self, query: str, *, limit: int = 10) -> list[SemanticSearchResult]:
        query = query.strip()
        if not query:
            return []

        self.flush_pending_chunks()
        rewritten_queries = expand_semantic_query(query)
        if len(rewritten_queries) == 1:
            scored_results = self._search_single_query_with_scores(query, limit=limit)
            self._log_v2_search_scores(scored_results=scored_results, query_variant_count=1)
            return [item.result for item in scored_results]

        per_query_limit = max(limit * FUSION_CANDIDATE_MULTIPLIER, limit)
        subquery_hits = [
            self._search_single_query_with_scores(
                subquery,
                limit=per_query_limit,
                candidate_limit=per_query_limit,
            )
            for subquery in rewritten_queries
        ]
        merged_hits = self._merge_query_variants_with_scores(
            subquery_hits,
            limit=limit,
            use_confidence_display=True,
        )
        self._log_v2_search_scores(scored_results=merged_hits, query_variant_count=len(rewritten_queries))
        return [item.result for item in merged_hits]

    def _search_single_query(
        self,
        query: str,
        *,
        limit: int,
        candidate_limit: int | None = None,
    ) -> list[SemanticSearchResult]:
        return [
            item.result
            for item in self._search_single_query_with_scores(
                query,
                limit=limit,
                candidate_limit=candidate_limit,
            )
        ]

    def _search_single_query_with_scores(
        self,
        query: str,
        *,
        limit: int,
        candidate_limit: int | None = None,
    ) -> list[_ScoredSearchResult]:
        resolved_candidate_limit = candidate_limit or max(limit * FUSION_CANDIDATE_MULTIPLIER, limit)
        chunk_hits = self._index.search(query, limit=max(limit * 5, resolved_candidate_limit))
        dense_hits = self._aggregate_hits_with_scores(chunk_hits, limit=resolved_candidate_limit)

        if self._lexical_service is None:
            return dense_hits[:limit]

        lexical_hits = self._lexical_service.search(query, limit=resolved_candidate_limit)
        if not lexical_hits:
            return dense_hits[:limit]

        return self._fuse_hits_with_scores(
            dense_hits,
            lexical_hits,
            limit=limit,
            use_confidence_display=True,
        )

    def flush_pending_chunks(self) -> None:
        if not self._pending_chunks_by_doc:
            return

        pending_chunks = [
            chunk
            for chunks in self._pending_chunks_by_doc.values()
            for chunk in chunks
        ]
        logger.info(
            "semantic_index_flush",
            extra={
                "event": "semantic_index_flush",
                "pending_chunk_count": len(pending_chunks),
            },
        )
        self._index.index_chunks(pending_chunks)
        self._pending_chunks_by_doc.clear()

    def _aggregate_hits(
        self, chunk_hits: list[ChunkSearchHit], *, limit: int
    ) -> list[SemanticSearchResult]:
        return [item.result for item in self._aggregate_hits_with_scores(chunk_hits, limit=limit)]

    def _aggregate_hits_with_scores(
        self,
        chunk_hits: list[ChunkSearchHit],
        *,
        limit: int,
    ) -> list[_ScoredSearchResult]:
        best_hit_by_doc: dict[str, ChunkSearchHit] = {}

        for hit in chunk_hits:
            doc_id = hit.chunk.doc_id
            current_best = best_hit_by_doc.get(doc_id)
            if current_best is None or hit.score > current_best.score:
                best_hit_by_doc[doc_id] = hit

        aggregated_hits = [
            (
                round(hit.score, 4),
                hit.chunk.doc_id,
                hit,
            )
            for hit in best_hit_by_doc.values()
        ]
        aggregated_hits.sort(key=lambda item: (-item[0], item[1]))
        return [
            self._build_scored_search_result(
                document_id=hit.chunk.doc_id,
                title=hit.chunk.title,
                snippet=_build_snippet(hit.chunk.text),
                raw_score=raw_score,
            )
            for raw_score, _, hit in aggregated_hits[:limit]
        ]

    def _fuse_hits(
        self,
        dense_hits: list[SemanticSearchResult],
        lexical_hits: list[SearchHit],
        *,
        limit: int,
    ) -> list[SemanticSearchResult]:
        scored_dense_hits = [_scored_result_from_display(hit) for hit in dense_hits]
        return [item.result for item in self._fuse_hits_with_scores(scored_dense_hits, lexical_hits, limit=limit)]

    def _fuse_hits_with_scores(
        self,
        dense_hits: list[_ScoredSearchResult],
        lexical_hits: list[SearchHit],
        *,
        limit: int,
        use_confidence_display: bool = False,
    ) -> list[_ScoredSearchResult]:
        dense_by_id = {hit.result.id: hit for hit in dense_hits}
        lexical_by_id = {hit.id: hit for hit in lexical_hits}
        dense_rrf_scores = _rank_scores([hit.result.id for hit in dense_hits])
        lexical_rrf_scores = _rank_scores([hit.id for hit in lexical_hits])
        max_lexical_score = max((hit.score for hit in lexical_hits), default=0.0)

        fused_hits: list[tuple[float, float, float, float, str, str, str]] = []
        candidate_ids = set(dense_by_id) | set(lexical_by_id)

        for document_id in candidate_ids:
            dense_rank = dense_rrf_scores.get(document_id, 0.0)
            lexical_rank = lexical_rrf_scores.get(document_id, 0.0)
            final_score = (
                self._fusion_dense_weight * dense_rank
                + self._fusion_lexical_weight * lexical_rank
            )

            dense_hit = dense_by_id.get(document_id)
            lexical_hit = lexical_by_id.get(document_id)
            display_score_basis = final_score
            if use_confidence_display:
                display_score_basis = _build_confidence_display_score(
                    dense_score=dense_hit.display_score_basis if dense_hit is not None else None,
                    lexical_score=lexical_hit.score if lexical_hit is not None else None,
                    max_lexical_score=max_lexical_score,
                    dense_weight=self._fusion_dense_weight,
                    lexical_weight=self._fusion_lexical_weight,
                )
            title, snippet = self._resolve_display_hit(
                document_id,
                dense_hit.result if dense_hit is not None else None,
                lexical_hit,
            )
            fused_hits.append(
                (
                    final_score,
                    display_score_basis,
                    dense_rank,
                    lexical_rank,
                    document_id,
                    title,
                    snippet,
                )
            )

        fused_hits.sort(key=lambda item: (-item[0], -item[2], -item[3], item[4]))
        if use_confidence_display:
            adjusted_display_scores = _enforce_descending_display_scores([item[1] for item in fused_hits])
            fused_hits = [
                (
                    raw_score,
                    adjusted_display_score,
                    dense_rank,
                    lexical_rank,
                    document_id,
                    title,
                    snippet,
                )
                for (raw_score, _, dense_rank, lexical_rank, document_id, title, snippet), adjusted_display_score in zip(
                    fused_hits,
                    adjusted_display_scores,
                )
            ]
        return [
            self._build_scored_search_result(
                document_id=document_id,
                title=title,
                snippet=snippet,
                raw_score=raw_score,
                display_score_basis=display_score_basis,
            )
            for raw_score, display_score_basis, _, _, document_id, title, snippet in fused_hits[:limit]
        ]

    def _resolve_display_hit(
        self,
        document_id: str,
        dense_hit: SemanticSearchResult | None,
        lexical_hit: SearchHit | None,
    ) -> tuple[str, str]:
        if dense_hit is not None:
            return dense_hit.title, dense_hit.snippet

        representative_chunk = self._index.get_representative_chunk(document_id)
        if representative_chunk is not None:
            return representative_chunk.title, _build_snippet(representative_chunk.text)

        if lexical_hit is not None:
            return lexical_hit.title, lexical_hit.snippet

        return document_id, ""

    def _merge_query_variants(
        self,
        subquery_hits: list[list[SemanticSearchResult]],
        *,
        limit: int,
    ) -> list[SemanticSearchResult]:
        scored_subquery_hits = [
            [_scored_result_from_display(hit) for hit in hits]
            for hits in subquery_hits
        ]
        return [item.result for item in self._merge_query_variants_with_scores(scored_subquery_hits, limit=limit)]

    def _merge_query_variants_with_scores(
        self,
        subquery_hits: list[list[_ScoredSearchResult]],
        *,
        limit: int,
        use_confidence_display: bool = False,
    ) -> list[_ScoredSearchResult]:
        query_weights = _query_variant_weights(len(subquery_hits))
        merged_hits_by_doc: dict[str, dict[str, object]] = {}

        for query_order, hits in enumerate(subquery_hits):
            query_weight = query_weights[query_order]
            for hit in hits:
                weighted_component = query_weight * hit.raw_score
                weighted_display_component = query_weight * hit.display_score_basis
                merged_hit = merged_hits_by_doc.setdefault(
                    hit.result.id,
                    {
                        "weighted_total_score": 0.0,
                        "weighted_display_score": 0.0,
                        "original_score": 0.0,
                        "best_component": 0.0,
                        "best_raw_score": 0.0,
                        "best_hit": hit.result,
                        "matched_scores": [],
                        "matched_display_scores": [],
                    },
                )
                merged_hit["weighted_total_score"] = float(merged_hit["weighted_total_score"]) + weighted_component
                merged_hit["weighted_display_score"] = (
                    float(merged_hit["weighted_display_score"]) + weighted_display_component
                )
                matched_scores = merged_hit["matched_scores"]
                if isinstance(matched_scores, list):
                    matched_scores.append(hit.raw_score)
                matched_display_scores = merged_hit["matched_display_scores"]
                if isinstance(matched_display_scores, list):
                    matched_display_scores.append(hit.display_score_basis)
                if query_order == 0:
                    merged_hit["original_score"] = hit.raw_score

                current_best_component = float(merged_hit["best_component"])
                current_best_raw_score = float(merged_hit["best_raw_score"])
                if (
                    weighted_component > current_best_component
                    or (
                        weighted_component == current_best_component
                        and hit.raw_score > current_best_raw_score
                    )
                ):
                    merged_hit["best_component"] = weighted_component
                    merged_hit["best_raw_score"] = hit.raw_score
                    merged_hit["best_hit"] = hit.result

        merged_hits: list[tuple[float, float, float, float, SemanticSearchResult]] = []
        for document_id, merged_hit in merged_hits_by_doc.items():
            best_hit = merged_hit["best_hit"]
            weighted_total_score = float(merged_hit["weighted_total_score"])
            weighted_display_score = float(merged_hit["weighted_display_score"])
            original_score = float(merged_hit["original_score"])
            best_component = float(merged_hit["best_component"])
            matched_scores = merged_hit["matched_scores"]
            matched_display_scores = merged_hit["matched_display_scores"]
            raw_score = _merge_variant_score(
                self._query_variant_merge_strategy,
                weighted_total_score=weighted_total_score,
                matched_scores=matched_scores if isinstance(matched_scores, list) else [],
            )
            display_score_basis = raw_score
            if use_confidence_display:
                display_score_basis = _merge_variant_score(
                    self._query_variant_merge_strategy,
                    weighted_total_score=weighted_display_score,
                    matched_scores=matched_display_scores if isinstance(matched_display_scores, list) else [],
                )
            merged_hits.append(
                (
                    raw_score,
                    display_score_basis,
                    original_score,
                    best_component,
                    best_hit,
                )
            )

        merged_hits.sort(key=lambda item: (-item[0], -item[2], -item[3], item[4].id))
        if use_confidence_display:
            adjusted_display_scores = _enforce_descending_display_scores([item[1] for item in merged_hits])
            merged_hits = [
                (
                    raw_score,
                    adjusted_display_score,
                    original_score,
                    best_component,
                    best_hit,
                )
                for (raw_score, _, original_score, best_component, best_hit), adjusted_display_score in zip(
                    merged_hits,
                    adjusted_display_scores,
                )
            ]
        return [
            self._build_scored_search_result(
                document_id=best_hit.id,
                title=best_hit.title,
                snippet=best_hit.snippet,
                raw_score=raw_score,
                display_score_basis=display_score_basis,
            )
            for raw_score, display_score_basis, _, _, best_hit in merged_hits[:limit]
        ]

    def _build_scored_search_result(
        self,
        *,
        document_id: str,
        title: str,
        snippet: str,
        raw_score: float,
        display_score_basis: float | None = None,
    ) -> _ScoredSearchResult:
        resolved_display_score_basis = _resolve_display_score_basis(raw_score if display_score_basis is None else display_score_basis)
        return _ScoredSearchResult(
            raw_score=raw_score,
            display_score_basis=resolved_display_score_basis,
            result=SemanticSearchResult(
                id=document_id,
                title=title,
                snippet=snippet,
                score=round(_transform_display_score(resolved_display_score_basis, self._display_score_temperature), 4),
            ),
        )

    def _log_v2_search_scores(
        self,
        *,
        scored_results: list[_ScoredSearchResult],
        query_variant_count: int,
    ) -> None:
        top1_raw_score = scored_results[0].raw_score if scored_results else None
        top1_display_score = scored_results[0].result.score if scored_results else None
        top1_top2_gap = (
            scored_results[0].raw_score - scored_results[1].raw_score
            if len(scored_results) >= 2
            else None
        )
        top1_top5_gap = (
            scored_results[0].raw_score - scored_results[4].raw_score
            if len(scored_results) >= 5
            else None
        )
        logger.info(
            "v2_search_scoring",
            extra={
                "event": "v2_search_scoring",
                "preset": self._score_experiment_preset,
                "strategy": self._query_variant_merge_strategy,
                "dense_weight": round(self._fusion_dense_weight, 4),
                "lexical_weight": round(self._fusion_lexical_weight, 4),
                "display_score_temperature": round(self._display_score_temperature, 4),
                "query_variant_count": query_variant_count,
                "result_count": len(scored_results),
                "top_result_id": scored_results[0].result.id if scored_results else None,
                "top1_raw_score": round(top1_raw_score, 4) if top1_raw_score is not None else None,
                "top1_display_score": top1_display_score,
                "top1_top2_gap": round(top1_top2_gap, 4) if top1_top2_gap is not None else None,
                "top1_top5_gap": round(top1_top5_gap, 4) if top1_top5_gap is not None else None,
            },
        )


def _build_snippet(text: str) -> str:
    if len(text) <= SNIPPET_MAX_CHARS:
        return text

    end = min(len(text), SNIPPET_MAX_CHARS)
    while end < len(text) and text[end] not in SNIPPET_BOUNDARIES:
        end += 1
    return f"{text[:end].strip()}..."


def _rank_scores(document_ids: list[str], k: int = 60) -> dict[str, float]:
    return {
        document_id: 1.0 / (k + rank + 1)
        for rank, document_id in enumerate(document_ids)
    }


def _query_variant_weights(query_count: int) -> tuple[float, ...]:
    if query_count in QUERY_VARIANT_WEIGHT_PRESETS:
        return QUERY_VARIANT_WEIGHT_PRESETS[query_count]

    if query_count <= len(DEFAULT_QUERY_VARIANT_WEIGHTS):
        return DEFAULT_QUERY_VARIANT_WEIGHTS[:query_count]

    extra_weights = (0.0,) * (query_count - len(DEFAULT_QUERY_VARIANT_WEIGHTS))
    return DEFAULT_QUERY_VARIANT_WEIGHTS + extra_weights


def _merge_variant_score(
    strategy: str,
    *,
    weighted_total_score: float,
    matched_scores: list[float],
) -> float:
    if strategy == "max_score":
        return max(matched_scores, default=0.0)
    if strategy == "top2_avg":
        top_scores = sorted(matched_scores, reverse=True)[:2]
        if not top_scores:
            return 0.0
        return sum(top_scores) / len(top_scores)
    return weighted_total_score


def _load_v2_score_runtime_config() -> V2ScoreRuntimeConfig:
    preset_name = _resolve_experiment_preset_name(os.getenv(V2_SCORE_EXPERIMENT_PRESET_ENV))
    preset = V2_SCORE_EXPERIMENT_PRESETS[preset_name]
    strategy = _resolve_env_merge_strategy(
        V2_QUERY_VARIANT_MERGE_STRATEGY_ENV,
        default=preset.query_variant_merge_strategy,
    )
    temperature = _resolve_env_float(
        V2_DISPLAY_SCORE_TEMPERATURE_ENV,
        default=preset.display_score_temperature,
        min_value=0.000001,
    )
    dense_weight = _resolve_env_float(
        V2_FUSION_DENSE_WEIGHT_ENV,
        default=preset.fusion_dense_weight,
        min_value=0.0,
        max_value=1.0,
    )
    lexical_weight = _resolve_env_float(
        V2_FUSION_LEXICAL_WEIGHT_ENV,
        default=preset.fusion_lexical_weight,
        min_value=0.0,
        max_value=1.0,
    )
    dense_weight, lexical_weight = _normalize_fusion_weights(
        dense_weight=dense_weight,
        lexical_weight=lexical_weight,
        default_dense=preset.fusion_dense_weight,
        default_lexical=preset.fusion_lexical_weight,
        context="env_v2_fusion_weights",
    )
    return V2ScoreRuntimeConfig(
        preset_name=preset_name,
        query_variant_merge_strategy=strategy,
        fusion_dense_weight=dense_weight,
        fusion_lexical_weight=lexical_weight,
        display_score_temperature=temperature,
    )


def _resolve_experiment_preset_name(raw_value: str | None) -> str:
    if raw_value is None:
        return DEFAULT_V2_SCORE_EXPERIMENT_PRESET

    preset_name = raw_value.strip().casefold()
    if preset_name in V2_SCORE_EXPERIMENT_PRESETS:
        return preset_name

    logger.warning(
        "v2_score_config_invalid_preset",
        extra={
            "event": "v2_score_config_invalid_preset",
            "env_var": V2_SCORE_EXPERIMENT_PRESET_ENV,
            "value": raw_value,
            "fallback": DEFAULT_V2_SCORE_EXPERIMENT_PRESET,
        },
    )
    return DEFAULT_V2_SCORE_EXPERIMENT_PRESET


def _resolve_query_variant_merge_strategy(strategy: str | None, *, default: str = QUERY_VARIANT_MERGE_STRATEGY) -> str:
    normalized = str(strategy).strip().casefold()
    if normalized in VALID_QUERY_VARIANT_MERGE_STRATEGIES:
        return normalized
    return default


def _resolve_env_merge_strategy(env_name: str, *, default: str) -> str:
    raw_value = os.getenv(env_name)
    if raw_value is None:
        return default

    strategy = _resolve_query_variant_merge_strategy(raw_value, default=default)
    if strategy != raw_value.strip().casefold():
        logger.warning(
            "v2_score_config_invalid_merge_strategy",
            extra={
                "event": "v2_score_config_invalid_merge_strategy",
                "env_var": env_name,
                "value": raw_value,
                "fallback": default,
            },
        )
    return strategy


def _resolve_display_score_temperature(temperature: float, *, default: float = DISPLAY_SCORE_TEMPERATURE) -> float:
    return _resolve_numeric_config(temperature, default=default, min_value=0.000001)


def _resolve_env_float(
    env_name: str,
    *,
    default: float,
    min_value: float | None = None,
    max_value: float | None = None,
) -> float:
    raw_value = os.getenv(env_name)
    if raw_value is None:
        return default

    parsed_value = _parse_float(raw_value)
    if parsed_value is None:
        logger.warning(
            "v2_score_config_invalid_float",
            extra={
                "event": "v2_score_config_invalid_float",
                "env_var": env_name,
                "value": raw_value,
                "fallback": default,
                "min_value": min_value,
                "max_value": max_value,
            },
        )
        return default

    if min_value is not None and parsed_value < min_value:
        logger.warning(
            "v2_score_config_invalid_float",
            extra={
                "event": "v2_score_config_invalid_float",
                "env_var": env_name,
                "value": raw_value,
                "fallback": default,
                "min_value": min_value,
                "max_value": max_value,
            },
        )
        return default
    if max_value is not None and parsed_value > max_value:
        logger.warning(
            "v2_score_config_invalid_float",
            extra={
                "event": "v2_score_config_invalid_float",
                "env_var": env_name,
                "value": raw_value,
                "fallback": default,
                "min_value": min_value,
                "max_value": max_value,
            },
        )
        return default

    return parsed_value


def _resolve_numeric_config(
    value: float | str,
    *,
    default: float,
    min_value: float | None = None,
    max_value: float | None = None,
) -> float:
    try:
        resolved_value = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(resolved_value):
        return default
    if min_value is not None and resolved_value < min_value:
        return default
    if max_value is not None and resolved_value > max_value:
        return default
    return resolved_value


def _transform_display_score(score: float, temperature: float) -> float:
    if not math.isfinite(score):
        return 0.0
    if temperature == 1.0:
        return score

    clamped_score = max(score, 0.0)
    transformed_score = clamped_score ** temperature
    if not math.isfinite(transformed_score) or transformed_score < 0.0:
        return 0.0
    return transformed_score


def _build_confidence_display_score(
    *,
    dense_score: float | None,
    lexical_score: float | None,
    max_lexical_score: float,
    dense_weight: float,
    lexical_weight: float,
) -> float:
    dense_component = _resolve_display_score_basis(dense_score) if dense_score is not None else 0.0
    lexical_component = _normalize_lexical_display_score(lexical_score, max_lexical_score)
    blended_score = dense_weight * dense_component + lexical_weight * lexical_component
    return _resolve_display_score_basis(blended_score)


def _normalize_lexical_display_score(score: float | None, max_lexical_score: float) -> float:
    if score is None or not math.isfinite(score) or score <= 0.0:
        return 0.0
    if not math.isfinite(max_lexical_score) or max_lexical_score <= 0.0:
        return 0.0
    return _resolve_display_score_basis(score / max_lexical_score)


def _resolve_display_score_basis(score: float) -> float:
    if not math.isfinite(score):
        return 0.0
    return min(max(score, 0.0), 1.0)


def _enforce_descending_display_scores(scores: list[float]) -> list[float]:
    adjusted_scores: list[float] = []

    for score in scores:
        resolved_score = _resolve_display_score_basis(score)
        if adjusted_scores and resolved_score >= adjusted_scores[-1]:
            resolved_score = max(adjusted_scores[-1] - DISPLAY_SCORE_MIN_STEP, 0.0)
        adjusted_scores.append(resolved_score)

    return adjusted_scores


def _normalize_fusion_weights(
    *,
    dense_weight: float,
    lexical_weight: float,
    default_dense: float,
    default_lexical: float,
    context: str,
) -> tuple[float, float]:
    total = dense_weight + lexical_weight
    if not math.isfinite(total) or total <= 0.0:
        logger.warning(
            "v2_score_config_invalid_weight_sum",
            extra={
                "event": "v2_score_config_invalid_weight_sum",
                "context": context,
                "dense_weight": dense_weight,
                "lexical_weight": lexical_weight,
                "fallback_dense_weight": default_dense,
                "fallback_lexical_weight": default_lexical,
            },
        )
        return default_dense, default_lexical
    if math.isclose(total, 1.0, rel_tol=1e-9, abs_tol=1e-9):
        return dense_weight, lexical_weight

    normalized_dense = dense_weight / total
    normalized_lexical = lexical_weight / total
    logger.warning(
        "v2_score_config_normalized_weights",
        extra={
            "event": "v2_score_config_normalized_weights",
            "context": context,
            "original_dense_weight": dense_weight,
            "original_lexical_weight": lexical_weight,
            "normalized_dense_weight": round(normalized_dense, 4),
            "normalized_lexical_weight": round(normalized_lexical, 4),
        },
    )
    return normalized_dense, normalized_lexical


def _scored_result_from_display(hit: SemanticSearchResult) -> _ScoredSearchResult:
    normalized_score = _resolve_display_score_basis(hit.score)
    return _ScoredSearchResult(
        raw_score=hit.score,
        display_score_basis=normalized_score,
        result=hit,
    )


def _parse_float(value: str) -> float | None:
    try:
        parsed_value = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed_value):
        return None
    return parsed_value


def _shutdown_component(component_name: str, component: object) -> None:
    shutdown = getattr(component, "shutdown", None)
    if not callable(shutdown):
        return

    try:
        cast_shutdown = shutdown_component(shutdown)
        cast_shutdown()
    except Exception:
        logger.exception(
            "semantic_component_shutdown_failed",
            extra={
                "event": "semantic_component_shutdown_failed",
                "component": component_name,
            },
        )


def shutdown_component(shutdown: Callable[..., Any]) -> Callable[[], Any]:
    return shutdown

import pytest

from app.indexing.chunker import SemanticChunk
from app.indexing.lexical_index import SearchHit
from app.indexing.semantic_index import ChunkSearchHit
from app.services.semantic_search_service import (
    DEFAULT_V2_SCORE_EXPERIMENT_PRESET,
    DISPLAY_SCORE_TEMPERATURE,
    FUSION_DENSE_WEIGHT,
    FUSION_LEXICAL_WEIGHT,
    QUERY_VARIANT_MERGE_STRATEGY,
    SemanticSearchResult,
    SemanticSearchService,
    V2_DISPLAY_SCORE_TEMPERATURE_ENV,
    V2_FUSION_DENSE_WEIGHT_ENV,
    V2_FUSION_LEXICAL_WEIGHT_ENV,
    V2_QUERY_VARIANT_MERGE_STRATEGY_ENV,
    V2_SCORE_EXPERIMENT_PRESET_ENV,
    V2_SCORE_EXPERIMENT_PRESETS,
    _rank_scores,
)


def _make_chunk(doc_id: str, title: str, text: str) -> SemanticChunk:
    return SemanticChunk(
        chunk_id=f"{doc_id}::chunk-001",
        doc_id=doc_id,
        title=title,
        section_path="",
        text=text,
        search_text=text,
    )


class StubChunker:
    def __init__(self, chunks_by_doc: dict[str, SemanticChunk]) -> None:
        self._chunks_by_doc = chunks_by_doc

    def chunk_document(self, document_id: str, html: str, *, title: str | None = None) -> list[SemanticChunk]:
        return [self._chunks_by_doc[document_id]]


class StubSemanticIndex:
    def __init__(self) -> None:
        self._chunks_by_doc: dict[str, SemanticChunk] = {}
        self._search_hits_by_query: dict[str, list[ChunkSearchHit]] = {}

    def index_chunks(self, chunks: list[SemanticChunk]) -> None:
        for chunk in chunks:
            self._chunks_by_doc[chunk.doc_id] = chunk

    def remove_document(self, doc_id: str) -> None:
        self._chunks_by_doc.pop(doc_id, None)

    def search(self, query: str, *, limit: int = 20) -> list[ChunkSearchHit]:
        return self._search_hits_by_query.get(query, [])[:limit]

    def get_representative_chunk(self, doc_id: str) -> SemanticChunk | None:
        return self._chunks_by_doc.get(doc_id)


class StubLexicalService:
    def __init__(self, hits_by_query: dict[str, list[SearchHit]]) -> None:
        self._hits_by_query = hits_by_query

    def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        return self._hits_by_query.get(query, [])[:limit]


def _clear_v2_score_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_name in (
        V2_SCORE_EXPERIMENT_PRESET_ENV,
        V2_QUERY_VARIANT_MERGE_STRATEGY_ENV,
        V2_DISPLAY_SCORE_TEMPERATURE_ENV,
        V2_FUSION_DENSE_WEIGHT_ENV,
        V2_FUSION_LEXICAL_WEIGHT_ENV,
    ):
        monkeypatch.delenv(env_name, raising=False)


def test_hybrid_fusion_promotes_broad_operational_matches() -> None:
    chunks_by_doc = {
        "backend": _make_chunk("backend", "后端服务 On-Call SOP", "后端服务出现故障，需要先恢复核心链路。"),
        "infra": _make_chunk("infra", "SRE基础设施 On-Call SOP", "基础设施异常会导致多个服务不可用。"),
        "network": _make_chunk("network", "网络与CDN On-Call SOP", "服务器证书与CDN回源异常。"),
        "noise": _make_chunk("noise", "测试平台 SOP", "测试平台发布异常。"),
    }
    index = StubSemanticIndex()
    lexical_service = StubLexicalService(
        {
            "服务器挂了": [
                SearchHit(id="backend", title="后端服务 On-Call SOP", snippet="backend", score=3.0),
                SearchHit(id="infra", title="SRE基础设施 On-Call SOP", snippet="infra", score=2.0),
                SearchHit(id="network", title="网络与CDN On-Call SOP", snippet="network", score=1.0),
            ]
        }
    )
    service = SemanticSearchService(
        chunker=StubChunker(chunks_by_doc),
        index=index,
        lexical_service=lexical_service,
    )

    for document_id in chunks_by_doc:
        service.ingest_document(document_id, f"<html>{document_id}</html>")
    service.warmup()

    index._search_hits_by_query["服务器挂了"] = [
        ChunkSearchHit(chunk=chunks_by_doc["network"], score=0.95),
        ChunkSearchHit(chunk=chunks_by_doc["backend"], score=0.89),
        ChunkSearchHit(chunk=chunks_by_doc["noise"], score=0.86),
        ChunkSearchHit(chunk=chunks_by_doc["infra"], score=0.84),
    ]

    hit_ids = [hit.id for hit in service.search("服务器挂了", limit=3)]

    assert "backend" in hit_ids[:3]
    assert "infra" in hit_ids[:3]
    assert "noise" not in hit_ids[:3]


def test_hybrid_fusion_keeps_sharp_semantic_match_on_top() -> None:
    chunks_by_doc = {
        "security": _make_chunk("security", "信息安全 On-Call SOP", "黑客攻击与入侵事件需要立即响应。"),
        "network": _make_chunk("network", "网络与CDN On-Call SOP", "网络攻击流量需要排查。"),
        "backend": _make_chunk("backend", "后端服务 On-Call SOP", "服务异常排查。"),
    }
    index = StubSemanticIndex()
    lexical_service = StubLexicalService(
        {
            "黑客攻击": [
                SearchHit(id="security", title="信息安全 On-Call SOP", snippet="security", score=3.0),
                SearchHit(id="network", title="网络与CDN On-Call SOP", snippet="network", score=2.0),
            ]
        }
    )
    service = SemanticSearchService(
        chunker=StubChunker(chunks_by_doc),
        index=index,
        lexical_service=lexical_service,
    )

    for document_id in chunks_by_doc:
        service.ingest_document(document_id, f"<html>{document_id}</html>")
    service.warmup()

    index._search_hits_by_query["黑客攻击"] = [
        ChunkSearchHit(chunk=chunks_by_doc["security"], score=0.98),
        ChunkSearchHit(chunk=chunks_by_doc["network"], score=0.70),
        ChunkSearchHit(chunk=chunks_by_doc["backend"], score=0.32),
    ]

    hits = service.search("黑客攻击", limit=3)

    assert hits[0].id == "security"


def test_rank_scores_uses_standard_rrf_smoothing() -> None:
    ranks = _rank_scores(["backend", "infra", "network"])

    assert ranks["backend"] == pytest.approx(1.0 / 61.0)
    assert ranks["infra"] == pytest.approx(1.0 / 62.0)
    assert ranks["network"] == pytest.approx(1.0 / 63.0)


def test_hybrid_fusion_uses_weighted_rrf_scores() -> None:
    service = SemanticSearchService()
    dense_hits = [
        SemanticSearchResult(id="backend", title="Backend", snippet="backend", score=0.99),
        SemanticSearchResult(id="infra", title="Infra", snippet="infra", score=0.98),
    ]
    lexical_hits = [
        SearchHit(id="infra", title="Infra", snippet="infra", score=3.0),
        SearchHit(id="backend", title="Backend", snippet="backend", score=2.0),
    ]

    hits = service._fuse_hits(dense_hits, lexical_hits, limit=2)

    expected_backend_score = round(
        FUSION_DENSE_WEIGHT * (1.0 / 61.0) + FUSION_LEXICAL_WEIGHT * (1.0 / 62.0),
        4,
    )
    expected_infra_score = round(
        FUSION_DENSE_WEIGHT * (1.0 / 62.0) + FUSION_LEXICAL_WEIGHT * (1.0 / 61.0),
        4,
    )

    assert [hit.id for hit in hits] == ["backend", "infra"]
    assert hits[0].score == expected_backend_score
    assert hits[1].score == expected_infra_score


def test_query_variant_merge_defaults_to_weighted_sum() -> None:
    subquery_hits = [
        [
            SemanticSearchResult(id="backend", title="Backend", snippet="backend", score=0.9),
            SemanticSearchResult(id="infra", title="Infra", snippet="infra", score=0.6),
        ],
        [
            SemanticSearchResult(id="backend", title="Backend", snippet="backend", score=0.3),
            SemanticSearchResult(id="infra", title="Infra", snippet="infra", score=0.8),
        ],
    ]
    default_service = SemanticSearchService()
    explicit_service = SemanticSearchService(query_variant_merge_strategy="weighted_sum")
    fallback_service = SemanticSearchService(query_variant_merge_strategy="not-a-real-strategy")

    default_hits = default_service._merge_query_variants(subquery_hits, limit=2)
    explicit_hits = explicit_service._merge_query_variants(subquery_hits, limit=2)
    fallback_hits = fallback_service._merge_query_variants(subquery_hits, limit=2)

    assert QUERY_VARIANT_MERGE_STRATEGY == "weighted_sum"
    assert [(hit.id, hit.score) for hit in default_hits] == [(hit.id, hit.score) for hit in explicit_hits]
    assert [(hit.id, hit.score) for hit in fallback_hits] == [(hit.id, hit.score) for hit in explicit_hits]


def test_query_variant_merge_max_score_differs_from_weighted_sum() -> None:
    subquery_hits = [
        [SemanticSearchResult(id="backend", title="Backend", snippet="backend", score=0.9)],
        [SemanticSearchResult(id="backend", title="Backend", snippet="backend", score=0.2)],
    ]
    weighted_hits = SemanticSearchService()._merge_query_variants(subquery_hits, limit=1)
    max_hits = SemanticSearchService(query_variant_merge_strategy="max_score")._merge_query_variants(
        subquery_hits,
        limit=1,
    )

    assert weighted_hits[0].id == max_hits[0].id == "backend"
    assert weighted_hits[0].score == pytest.approx(0.725)
    assert max_hits[0].score == pytest.approx(0.9)
    assert max_hits[0].score > weighted_hits[0].score


def test_query_variant_merge_top2_avg_single_hit_uses_single_score() -> None:
    subquery_hits = [
        [SemanticSearchResult(id="backend", title="Backend", snippet="backend", score=0.83)],
        [],
    ]

    hits = SemanticSearchService(query_variant_merge_strategy="top2_avg")._merge_query_variants(
        subquery_hits,
        limit=1,
    )

    assert hits[0].score == pytest.approx(0.83)


def test_query_variant_merge_top2_avg_two_hits_averages_both_scores() -> None:
    subquery_hits = [
        [SemanticSearchResult(id="backend", title="Backend", snippet="backend", score=0.9)],
        [SemanticSearchResult(id="backend", title="Backend", snippet="backend", score=0.3)],
    ]

    hits = SemanticSearchService(query_variant_merge_strategy="top2_avg")._merge_query_variants(
        subquery_hits,
        limit=1,
    )

    assert hits[0].score == pytest.approx(0.6)


def test_query_variant_merge_top2_avg_uses_best_two_scores_for_multi_hit_case() -> None:
    subquery_hits = [
        [SemanticSearchResult(id="backend", title="Backend", snippet="backend", score=0.9)],
        [SemanticSearchResult(id="backend", title="Backend", snippet="backend", score=0.2)],
        [SemanticSearchResult(id="backend", title="Backend", snippet="backend", score=0.7)],
    ]

    hits = SemanticSearchService(query_variant_merge_strategy="top2_avg")._merge_query_variants(
        subquery_hits,
        limit=1,
    )

    assert hits[0].score == pytest.approx(0.8)


def test_display_score_temperature_stretches_scores_without_changing_ranking() -> None:
    subquery_hits = [
        [
            SemanticSearchResult(id="backend", title="Backend", snippet="backend", score=0.9),
            SemanticSearchResult(id="infra", title="Infra", snippet="infra", score=0.64),
        ],
        [
            SemanticSearchResult(id="backend", title="Backend", snippet="backend", score=0.4),
            SemanticSearchResult(id="infra", title="Infra", snippet="infra", score=0.36),
        ],
    ]
    raw_hits = SemanticSearchService()._merge_query_variants(subquery_hits, limit=2)
    stretched_hits = SemanticSearchService(display_score_temperature=0.5)._merge_query_variants(
        subquery_hits,
        limit=2,
    )

    assert DISPLAY_SCORE_TEMPERATURE == 1.0
    assert [hit.id for hit in stretched_hits] == [hit.id for hit in raw_hits]
    assert stretched_hits[0].score == pytest.approx(raw_hits[0].score ** 0.5, abs=1e-4)
    assert stretched_hits[1].score == pytest.approx(raw_hits[1].score ** 0.5, abs=1e-4)
    assert stretched_hits[0].score > stretched_hits[1].score


def test_v2_runtime_config_defaults_match_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_v2_score_env(monkeypatch)

    service = SemanticSearchService()

    assert service._score_experiment_preset == DEFAULT_V2_SCORE_EXPERIMENT_PRESET
    assert service._query_variant_merge_strategy == QUERY_VARIANT_MERGE_STRATEGY
    assert service._fusion_dense_weight == pytest.approx(FUSION_DENSE_WEIGHT)
    assert service._fusion_lexical_weight == pytest.approx(FUSION_LEXICAL_WEIGHT)
    assert service._display_score_temperature == pytest.approx(DISPLAY_SCORE_TEMPERATURE)


def test_v2_runtime_config_uses_named_preset(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_v2_score_env(monkeypatch)
    monkeypatch.setenv(V2_SCORE_EXPERIMENT_PRESET_ENV, "separation_soft")

    service = SemanticSearchService()
    preset = V2_SCORE_EXPERIMENT_PRESETS["separation_soft"]

    assert service._score_experiment_preset == "separation_soft"
    assert service._query_variant_merge_strategy == preset.query_variant_merge_strategy
    assert service._fusion_dense_weight == pytest.approx(preset.fusion_dense_weight)
    assert service._fusion_lexical_weight == pytest.approx(preset.fusion_lexical_weight)
    assert service._display_score_temperature == pytest.approx(preset.display_score_temperature)


def test_v2_runtime_config_env_overrides_beat_preset(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_v2_score_env(monkeypatch)
    monkeypatch.setenv(V2_SCORE_EXPERIMENT_PRESET_ENV, "separation_strong")
    monkeypatch.setenv(V2_QUERY_VARIANT_MERGE_STRATEGY_ENV, "top2_avg")
    monkeypatch.setenv(V2_DISPLAY_SCORE_TEMPERATURE_ENV, "0.95")
    monkeypatch.setenv(V2_FUSION_DENSE_WEIGHT_ENV, "0.6")
    monkeypatch.setenv(V2_FUSION_LEXICAL_WEIGHT_ENV, "0.4")

    service = SemanticSearchService()

    assert service._score_experiment_preset == "separation_strong"
    assert service._query_variant_merge_strategy == "top2_avg"
    assert service._fusion_dense_weight == pytest.approx(0.6)
    assert service._fusion_lexical_weight == pytest.approx(0.4)
    assert service._display_score_temperature == pytest.approx(0.95)


def test_v2_runtime_config_invalid_env_values_fall_back_to_safe_defaults(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _clear_v2_score_env(monkeypatch)
    monkeypatch.setenv(V2_SCORE_EXPERIMENT_PRESET_ENV, "separation_soft")
    monkeypatch.setenv(V2_QUERY_VARIANT_MERGE_STRATEGY_ENV, "bogus")
    monkeypatch.setenv(V2_DISPLAY_SCORE_TEMPERATURE_ENV, "0")
    monkeypatch.setenv(V2_FUSION_DENSE_WEIGHT_ENV, "oops")
    monkeypatch.setenv(V2_FUSION_LEXICAL_WEIGHT_ENV, "2")

    caplog.set_level("WARNING")
    service = SemanticSearchService()
    preset = V2_SCORE_EXPERIMENT_PRESETS["separation_soft"]

    assert service._score_experiment_preset == "separation_soft"
    assert service._query_variant_merge_strategy == preset.query_variant_merge_strategy
    assert service._fusion_dense_weight == pytest.approx(preset.fusion_dense_weight)
    assert service._fusion_lexical_weight == pytest.approx(preset.fusion_lexical_weight)
    assert service._display_score_temperature == pytest.approx(preset.display_score_temperature)

    logged_events = [record.msg for record in caplog.records]
    assert "v2_score_config_invalid_merge_strategy" in logged_events
    assert logged_events.count("v2_score_config_invalid_float") >= 3


def test_v2_runtime_config_normalizes_env_fusion_weights(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _clear_v2_score_env(monkeypatch)
    monkeypatch.setenv(V2_FUSION_DENSE_WEIGHT_ENV, "0.8")
    monkeypatch.setenv(V2_FUSION_LEXICAL_WEIGHT_ENV, "0.4")

    caplog.set_level("WARNING")
    service = SemanticSearchService()

    assert service._fusion_dense_weight == pytest.approx(2.0 / 3.0)
    assert service._fusion_lexical_weight == pytest.approx(1.0 / 3.0)
    assert "v2_score_config_normalized_weights" in [record.msg for record in caplog.records]


def test_search_returns_confidence_style_scores_with_visible_separation() -> None:
    chunks_by_doc = {
        "security": _make_chunk("security", "信息安全 On-Call SOP", "黑客攻击与入侵事件需要立即响应。"),
        "network": _make_chunk("network", "网络与CDN On-Call SOP", "网络攻击流量需要排查。"),
        "backend": _make_chunk("backend", "后端服务 On-Call SOP", "服务异常排查。"),
    }
    index = StubSemanticIndex()
    lexical_service = StubLexicalService(
        {
            "黑客攻击": [
                SearchHit(id="security", title="信息安全 On-Call SOP", snippet="security", score=3.0),
                SearchHit(id="network", title="网络与CDN On-Call SOP", snippet="network", score=2.0),
            ]
        }
    )
    service = SemanticSearchService(
        chunker=StubChunker(chunks_by_doc),
        index=index,
        lexical_service=lexical_service,
    )

    for document_id in chunks_by_doc:
        service.ingest_document(document_id, f"<html>{document_id}</html>")
    service.warmup()

    index._search_hits_by_query["黑客攻击"] = [
        ChunkSearchHit(chunk=chunks_by_doc["security"], score=0.98),
        ChunkSearchHit(chunk=chunks_by_doc["network"], score=0.70),
        ChunkSearchHit(chunk=chunks_by_doc["backend"], score=0.32),
    ]

    hits = service.search("黑客攻击", limit=3)

    assert [hit.id for hit in hits] == ["security", "network", "backend"]
    assert hits[0].score == pytest.approx(0.986, abs=1e-4)
    assert hits[1].score == pytest.approx(0.69, abs=1e-4)
    assert hits[2].score == pytest.approx(0.224, abs=1e-4)
    assert hits[0].score > hits[1].score > hits[2].score


def test_query_rewrite_max_score_keeps_order_but_no_longer_collapses_display_scores() -> None:
    chunks_by_doc = {
        "backend": _make_chunk("backend", "后端服务 On-Call SOP", "后端服务挂了，需要先恢复核心链路。"),
        "infra": _make_chunk("infra", "SRE基础设施 On-Call SOP", "SRE 集群故障会导致多个服务不可用。"),
        "platform": _make_chunk("platform", "平台可用性 SOP", "服务不可用时需要做平台降级。"),
    }
    index = StubSemanticIndex()
    lexical_service = StubLexicalService(
        {
            "服务器挂了": [
                SearchHit(id="backend", title="后端服务 On-Call SOP", snippet="backend", score=3.0),
                SearchHit(id="infra", title="SRE基础设施 On-Call SOP", snippet="infra", score=2.9),
                SearchHit(id="platform", title="平台可用性 SOP", snippet="platform", score=2.8),
            ],
            "后端服务挂了": [
                SearchHit(id="backend", title="后端服务 On-Call SOP", snippet="backend", score=3.0),
                SearchHit(id="infra", title="SRE基础设施 On-Call SOP", snippet="infra", score=1.0),
            ],
            "SRE 集群故障": [
                SearchHit(id="infra", title="SRE基础设施 On-Call SOP", snippet="infra", score=3.0),
                SearchHit(id="backend", title="后端服务 On-Call SOP", snippet="backend", score=1.0),
            ],
            "服务不可用": [
                SearchHit(id="platform", title="平台可用性 SOP", snippet="platform", score=3.0),
                SearchHit(id="backend", title="后端服务 On-Call SOP", snippet="backend", score=1.0),
            ],
        }
    )
    service = SemanticSearchService(
        chunker=StubChunker(chunks_by_doc),
        index=index,
        lexical_service=lexical_service,
        fusion_dense_weight=0.85,
        fusion_lexical_weight=0.15,
        query_variant_merge_strategy="max_score",
        display_score_temperature=1.0,
    )

    for document_id in chunks_by_doc:
        service.ingest_document(document_id, f"<html>{document_id}</html>")
    service.warmup()

    index._search_hits_by_query["服务器挂了"] = [
        ChunkSearchHit(chunk=chunks_by_doc["backend"], score=0.80),
        ChunkSearchHit(chunk=chunks_by_doc["infra"], score=0.79),
        ChunkSearchHit(chunk=chunks_by_doc["platform"], score=0.78),
    ]
    index._search_hits_by_query["后端服务挂了"] = [
        ChunkSearchHit(chunk=chunks_by_doc["backend"], score=0.99),
        ChunkSearchHit(chunk=chunks_by_doc["infra"], score=0.65),
    ]
    index._search_hits_by_query["SRE 集群故障"] = [
        ChunkSearchHit(chunk=chunks_by_doc["infra"], score=0.98),
        ChunkSearchHit(chunk=chunks_by_doc["backend"], score=0.60),
    ]
    index._search_hits_by_query["服务不可用"] = [
        ChunkSearchHit(chunk=chunks_by_doc["platform"], score=0.97),
        ChunkSearchHit(chunk=chunks_by_doc["backend"], score=0.58),
    ]

    hits = service.search("服务器挂了", limit=3)

    assert [hit.id for hit in hits] == ["backend", "infra", "platform"]
    assert hits[0].score == pytest.approx(0.9915, abs=1e-4)
    assert hits[1].score == pytest.approx(0.983, abs=1e-4)
    assert hits[2].score == pytest.approx(0.9745, abs=1e-4)
    assert hits[0].score > hits[1].score > hits[2].score

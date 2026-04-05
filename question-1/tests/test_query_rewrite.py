from app.indexing.chunker import SemanticChunk
from app.indexing.semantic_index import ChunkSearchHit
from app.services.query_rewrite import expand_semantic_query
from app.services.semantic_search_service import SemanticSearchService


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


class RecordingSemanticIndex:
    def __init__(self) -> None:
        self._chunks_by_doc: dict[str, SemanticChunk] = {}
        self._search_hits_by_query: dict[str, list[ChunkSearchHit]] = {}
        self.search_calls: list[str] = []

    def index_chunks(self, chunks: list[SemanticChunk]) -> None:
        for chunk in chunks:
            self._chunks_by_doc[chunk.doc_id] = chunk

    def remove_document(self, doc_id: str) -> None:
        self._chunks_by_doc.pop(doc_id, None)

    def search(self, query: str, *, limit: int = 20) -> list[ChunkSearchHit]:
        self.search_calls.append(query)
        return self._search_hits_by_query.get(query, [])[:limit]

    def get_representative_chunk(self, doc_id: str) -> SemanticChunk | None:
        return self._chunks_by_doc.get(doc_id)


def test_expand_semantic_query_for_broad_outage_query() -> None:
    assert expand_semantic_query("服务器挂了") == [
        "服务器挂了",
        "后端服务挂了",
        "SRE 集群故障",
        "服务不可用",
    ]


def test_expand_semantic_query_keeps_sharp_query_unchanged() -> None:
    assert expand_semantic_query("黑客攻击") == ["黑客攻击"]


def test_query_rewrite_promotes_backend_and_infra_docs() -> None:
    chunks_by_doc = {
        "backend": _make_chunk("backend", "后端服务 On-Call SOP", "后端服务不可用。"),
        "infra": _make_chunk("infra", "SRE基础设施 On-Call SOP", "Kubernetes 集群故障。"),
        "network": _make_chunk("network", "网络与CDN On-Call SOP", "负载均衡回源异常。"),
    }
    index = RecordingSemanticIndex()
    service = SemanticSearchService(chunker=StubChunker(chunks_by_doc), index=index)

    for document_id in chunks_by_doc:
        service.ingest_document(document_id, f"<html>{document_id}</html>")
    service.warmup()

    index._search_hits_by_query["服务器挂了"] = [
        ChunkSearchHit(chunk=chunks_by_doc["network"], score=0.97),
        ChunkSearchHit(chunk=chunks_by_doc["backend"], score=0.70),
    ]
    index._search_hits_by_query["后端服务挂了"] = [
        ChunkSearchHit(chunk=chunks_by_doc["backend"], score=0.99),
    ]
    index._search_hits_by_query["SRE 集群故障"] = [
        ChunkSearchHit(chunk=chunks_by_doc["infra"], score=0.98),
    ]
    index._search_hits_by_query["服务不可用"] = [
        ChunkSearchHit(chunk=chunks_by_doc["backend"], score=0.88),
        ChunkSearchHit(chunk=chunks_by_doc["infra"], score=0.87),
    ]

    hit_ids = [hit.id for hit in service.search("服务器挂了", limit=3)]

    assert index.search_calls == ["服务器挂了", "后端服务挂了", "SRE 集群故障", "服务不可用"]
    assert "backend" in hit_ids[:3]
    assert "infra" in hit_ids[:3]


def test_query_rewrite_keeps_broad_query_scores_differentiated() -> None:
    chunks_by_doc = {
        "backend": _make_chunk("backend", "后端服务 On-Call SOP", "后端服务不可用。"),
        "infra": _make_chunk("infra", "SRE基础设施 On-Call SOP", "Kubernetes 集群故障。"),
        "network": _make_chunk("network", "网络与CDN On-Call SOP", "负载均衡回源异常。"),
    }
    index = RecordingSemanticIndex()
    service = SemanticSearchService(chunker=StubChunker(chunks_by_doc), index=index)

    for document_id in chunks_by_doc:
        service.ingest_document(document_id, f"<html>{document_id}</html>")
    service.warmup()

    index._search_hits_by_query["服务器挂了"] = [
        ChunkSearchHit(chunk=chunks_by_doc["network"], score=1.0),
        ChunkSearchHit(chunk=chunks_by_doc["backend"], score=0.9),
        ChunkSearchHit(chunk=chunks_by_doc["infra"], score=0.85),
    ]
    index._search_hits_by_query["后端服务挂了"] = [
        ChunkSearchHit(chunk=chunks_by_doc["backend"], score=1.0),
    ]
    index._search_hits_by_query["SRE 集群故障"] = [
        ChunkSearchHit(chunk=chunks_by_doc["infra"], score=1.0),
    ]
    index._search_hits_by_query["服务不可用"] = [
        ChunkSearchHit(chunk=chunks_by_doc["backend"], score=1.0),
        ChunkSearchHit(chunk=chunks_by_doc["infra"], score=0.95),
    ]

    hits = service.search("服务器挂了", limit=3)
    top_scores = [hit.score for hit in hits[:3]]
    hit_ids = [hit.id for hit in hits[:3]]

    assert {"backend", "infra"}.issubset({hit.id for hit in hits[:3]})
    assert not (hit_ids.index("network") < hit_ids.index("backend") and hit_ids.index("network") < hit_ids.index("infra"))
    assert len(set(top_scores)) > 1


def test_query_rewrite_does_not_expand_sharp_query_search() -> None:
    chunks_by_doc = {
        "security": _make_chunk("security", "信息安全 On-Call SOP", "黑客攻击与入侵事件。"),
        "network": _make_chunk("network", "网络与CDN On-Call SOP", "攻击流量排查。"),
    }
    index = RecordingSemanticIndex()
    service = SemanticSearchService(chunker=StubChunker(chunks_by_doc), index=index)

    for document_id in chunks_by_doc:
        service.ingest_document(document_id, f"<html>{document_id}</html>")
    service.warmup()

    index._search_hits_by_query["黑客攻击"] = [
        ChunkSearchHit(chunk=chunks_by_doc["security"], score=0.99),
        ChunkSearchHit(chunk=chunks_by_doc["network"], score=0.70),
    ]

    hits = service.search("黑客攻击", limit=3)

    assert index.search_calls == ["黑客攻击"]
    assert hits[0].id == "security"

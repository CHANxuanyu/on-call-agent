def test_oom_query_returns_sop_001(document_service) -> None:
    hits = document_service.search("OOM")
    hit_ids = [hit.id for hit in hits]

    assert hits
    assert "sop-001" in hit_ids[:3]
    matched_hit = next(hit for hit in hits if hit.id == "sop-001")
    assert "OOM" in matched_hit.snippet or "OutOfMemoryError" in matched_hit.snippet


def test_fault_query_returns_multiple_documents(document_service) -> None:
    hits = document_service.search("故障")
    hit_ids = {hit.id for hit in hits}

    assert len(hits) >= 5
    assert {"sop-001", "sop-003", "sop-010"}.issubset(hit_ids)


def test_replication_query_returns_empty_results(document_service) -> None:
    assert document_service.search("replication") == []


def test_cdn_query_returns_frontend_and_network_docs(document_service) -> None:
    hit_ids = [hit.id for hit in document_service.search("CDN")]

    assert "sop-003" in hit_ids
    assert "sop-010" in hit_ids


def test_ampersand_query_preserves_symbol_search(document_service) -> None:
    hits = document_service.search("&")
    hit_ids = [hit.id for hit in hits]

    assert "sop-003" in hit_ids
    assert "sop-010" in hit_ids
    assert all(hit.score > 0 for hit in hits)


def test_full_width_api_query_matches_normalized_document_text(document_service) -> None:
    document_service.ingest_document(
        "sop-unicode-query",
        """
        <html>
            <body>
                <p>Use API/v1 for the read-only health endpoint.</p>
            </body>
        </html>
        """,
    )
    hit_ids = [hit.id for hit in document_service.search("ＡＰＩ／v1")]

    assert "sop-unicode-query" in hit_ids


def test_full_width_ampersand_query_matches_symbol_search(document_service) -> None:
    hit_ids = [hit.id for hit in document_service.search("＆")]

    assert "sop-003" in hit_ids
    assert "sop-010" in hit_ids

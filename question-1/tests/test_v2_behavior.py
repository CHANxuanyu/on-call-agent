def test_semantic_query_for_server_outage_returns_backend_and_sre_docs(semantic_search_service) -> None:
    hit_ids = [hit.id for hit in semantic_search_service.search("服务器挂了")]

    assert "sop-001" in hit_ids[:3]
    assert "sop-004" in hit_ids[:3]


def test_semantic_query_for_hacker_attack_returns_security_doc(semantic_search_service) -> None:
    hit_ids = [hit.id for hit in semantic_search_service.search("黑客攻击")]

    assert "sop-005" in hit_ids[:3]


def test_semantic_query_for_ml_model_issue_returns_ai_doc(semantic_search_service) -> None:
    hit_ids = [hit.id for hit in semantic_search_service.search("机器学习模型出问题")]

    assert "sop-008" in hit_ids[:3]

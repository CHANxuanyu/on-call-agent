def test_v2_page_renders_search_ui(v2_client) -> None:
    response = v2_client.get("/v2")

    assert response.status_code == 200
    assert 'id="search-query"' in response.text
    assert "Semantic SOP Search" in response.text


def test_v2_search_returns_phase2_response_shape(v2_client) -> None:
    response = v2_client.get("/v2/search", params={"q": "黑客攻击"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "黑客攻击"
    assert payload["results"]
    first_result = payload["results"][0]
    assert set(first_result) == {"id", "title", "snippet", "score"}
    assert isinstance(first_result["score"], float)


def test_v2_score_changes_do_not_alter_v1_or_v3_contracts(client) -> None:
    v1_response = client.get("/v1/search", params={"q": "故障"})
    v3_response = client.post("/v3/chat", json={"message": "黑客攻击"})

    assert v1_response.status_code == 200
    v1_payload = v1_response.json()
    assert set(v1_payload) == {"query", "results"}
    assert set(v1_payload["results"][0]) == {"id", "title", "snippet", "score"}

    assert v3_response.status_code == 200
    v3_payload = v3_response.json()
    assert set(v3_payload) == {"session_id", "assistant_message", "tool_calls", "consulted_files", "history"}

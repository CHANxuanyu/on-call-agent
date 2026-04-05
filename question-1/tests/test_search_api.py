def test_v1_page_renders_search_ui(client) -> None:
    response = client.get("/v1")

    assert response.status_code == 200
    assert 'id="search-query"' in response.text
    assert "On-Call SOP Search" in response.text


def test_post_document_indexes_visible_text(client) -> None:
    response = client.post(
        "/v1/documents",
        json={
            "id": "sop-custom",
            "html": """
            <html>
                <head><title>Custom &amp; SOP</title></head>
                <body>
                    <h1>Ignored fallback</h1>
                    <p>Primary &amp; backup path is active.</p>
                    <script>const secret = "replication";</script>
                </body>
            </html>
            """,
        },
    )

    assert response.status_code == 201
    assert response.json() == {"id": "sop-custom", "title": "Custom & SOP"}

    search_response = client.get("/v1/search", params={"q": "backup"})
    assert search_response.status_code == 200
    assert search_response.json()["results"][0]["id"] == "sop-custom"

    hidden_term_response = client.get("/v1/search", params={"q": "replication"})
    assert hidden_term_response.status_code == 200
    result_ids = {result["id"] for result in hidden_term_response.json()["results"]}
    assert "sop-custom" not in result_ids


def test_search_api_returns_scores_in_descending_order(client) -> None:
    response = client.get("/v1/search", params={"q": "故障"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "故障"
    assert len(payload["results"]) >= 5
    scores = [result["score"] for result in payload["results"]]
    assert scores == sorted(scores, reverse=True)

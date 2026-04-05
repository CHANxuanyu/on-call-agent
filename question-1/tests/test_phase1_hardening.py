from __future__ import annotations

from app.core.html_parser import parse_html_document
from app.data_store.in_memory_store import InMemoryDocumentStore
from app.indexing.lexical_index import BM25LexicalIndex
from app.indexing.tokenizer import Tokenizer
from app.services.document_service import DocumentService


def _build_service() -> DocumentService:
    return DocumentService(
        store=InMemoryDocumentStore(),
        index=BM25LexicalIndex(tokenizer=Tokenizer()),
    )


def test_ingest_empty_or_bodyless_html() -> None:
    service = _build_service()

    for document_id, html in (
        ("empty-doc", ""),
        ("html-only-doc", "<html></html>"),
        ("body-only-doc", "<body></body>"),
    ):
        stored_document = service.ingest_document(document_id, html)

        assert stored_document.id == document_id
        assert stored_document.title == document_id
        assert stored_document.visible_text == ""

    assert service.search("phase1-hardening-random-token") == []


def test_duplicate_document_id_replaces_or_rejects_consistently(client) -> None:
    initial_response = client.post(
        "/v1/documents",
        json={
            "id": "sop-dup-phase1",
            "html": "<html><body><p>alpha-legacy-dup marker</p></body></html>",
        },
    )
    replacement_response = client.post(
        "/v1/documents",
        json={
            "id": "sop-dup-phase1",
            "html": "<html><head><title>Replacement SOP</title></head><body><p>beta-fresh-dup marker</p></body></html>",
        },
    )

    assert initial_response.status_code == 201
    assert replacement_response.status_code == 201
    assert replacement_response.json() == {"id": "sop-dup-phase1", "title": "Replacement SOP"}

    old_hit_ids = {
        result["id"] for result in client.get("/v1/search", params={"q": "alpha-legacy-dup"}).json()["results"]
    }
    new_hit_ids = {
        result["id"] for result in client.get("/v1/search", params={"q": "beta-fresh-dup"}).json()["results"]
    }

    assert "sop-dup-phase1" not in old_hit_ids
    assert "sop-dup-phase1" in new_hit_ids


def test_blank_query_service_returns_empty_results(document_service) -> None:
    assert document_service.search("") == []
    assert document_service.search("   ") == []


def test_blank_query_api_returns_empty_results(client) -> None:
    blank_response = client.get("/v1/search", params={"q": ""})
    whitespace_response = client.get("/v1/search", params={"q": "   "})

    assert blank_response.status_code == 200
    assert blank_response.json() == {"query": "", "results": []}

    assert whitespace_response.status_code == 200
    assert whitespace_response.json() == {"query": "   ", "results": []}


def test_malformed_html_does_not_leak_head_or_script_text() -> None:
    parsed = parse_html_document(
        document_id="malformed-doc",
        html="""
        <html>
            <head>
                <title>Head Title</title>
                <meta name="description" content="head-only-marker">
                <script>const leakScriptToken = "should-not-leak";</script>
            </head>
            <div>
                <h1>Visible Incident</h1>
                <p>Recovered body text
            <script>window.replication = "also-hidden";</script>
        """,
    )

    assert parsed.title == "Head Title"
    assert "Visible Incident" in parsed.visible_text
    assert "Recovered body text" in parsed.visible_text
    assert "Head Title" not in parsed.visible_text
    assert "head-only-marker" not in parsed.visible_text
    assert "should-not-leak" not in parsed.visible_text
    assert "also-hidden" not in parsed.visible_text

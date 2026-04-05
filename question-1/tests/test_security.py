from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.agent_service import AgentService
from app.services.semantic_search_service import SemanticSearchResult


class StubPhase2SemanticService:
    def set_lexical_service(self, lexical_service) -> None:
        del lexical_service

    def ingest_document(self, document_id: str, html: str) -> list[object]:
        del document_id, html
        return []

    def load_documents_from_directory(self, directory) -> int:
        del directory
        return 0

    def warmup(self) -> None:
        return None

    def search(self, query: str, *, limit: int = 10) -> list[SemanticSearchResult]:
        del query, limit
        return []


def test_protected_endpoints_allow_requests_when_api_key_is_unset(tmp_path) -> None:
    _write_security_corpus(tmp_path)
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        document_response = client.post(
            "/v1/documents",
            json={
                "id": "sop-custom",
                "html": "<html><head><title>Custom SOP</title></head><body><p>custom body</p></body></html>",
            },
        )
        chat_response = client.post("/v3/chat", json={"message": "黑客攻击"})

    assert document_response.status_code == 201
    assert chat_response.status_code == 200


def test_v1_document_write_requires_correct_api_key_when_configured(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("API_KEY", "top-secret")
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        missing_key = client.post(
            "/v1/documents",
            json={
                "id": "sop-custom",
                "html": "<html><body><p>custom body</p></body></html>",
            },
        )
        wrong_key = client.post(
            "/v1/documents",
            headers={"X-API-Key": "wrong-secret"},
            json={
                "id": "sop-custom",
                "html": "<html><body><p>custom body</p></body></html>",
            },
        )
        correct_key = client.post(
            "/v1/documents",
            headers={"X-API-Key": "top-secret"},
            json={
                "id": "sop-custom",
                "html": "<html><head><title>Custom SOP</title></head><body><p>custom body</p></body></html>",
            },
        )

    assert missing_key.status_code == 401
    assert missing_key.json() == {"detail": "unauthorized"}
    assert wrong_key.status_code == 401
    assert wrong_key.json() == {"detail": "unauthorized"}
    assert correct_key.status_code == 201


def test_v3_chat_requires_correct_api_key_when_configured(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("API_KEY", "top-secret")
    _write_security_corpus(tmp_path)
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        missing_key = client.post("/v3/chat", json={"message": "黑客攻击"})
        wrong_key = client.post(
            "/v3/chat",
            headers={"X-API-Key": "wrong-secret"},
            json={"message": "黑客攻击"},
        )
        correct_key = client.post(
            "/v3/chat",
            headers={"X-API-Key": "top-secret"},
            json={"message": "黑客攻击"},
        )

    assert missing_key.status_code == 401
    assert missing_key.json() == {"detail": "unauthorized"}
    assert wrong_key.status_code == 401
    assert wrong_key.json() == {"detail": "unauthorized"}
    assert correct_key.status_code == 200


def test_v3_history_requires_correct_api_key_when_configured(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("API_KEY", "top-secret")
    _write_security_corpus(tmp_path)
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        chat = client.post(
            "/v3/chat",
            headers={"X-API-Key": "top-secret"},
            json={"message": "黑客攻击"},
        )
        session_id = chat.json()["session_id"]
        missing_key = client.get(f"/v3/history/{session_id}")
        wrong_key = client.get(
            f"/v3/history/{session_id}",
            headers={"X-API-Key": "wrong-secret"},
        )
        correct_key = client.get(
            f"/v3/history/{session_id}",
            headers={"X-API-Key": "top-secret"},
        )

    assert missing_key.status_code == 401
    assert missing_key.json() == {"detail": "unauthorized"}
    assert wrong_key.status_code == 401
    assert wrong_key.json() == {"detail": "unauthorized"}
    assert correct_key.status_code == 200
    assert [turn["role"] for turn in correct_key.json()["history"]] == ["user", "assistant"]


def test_v3_chat_rate_limit_returns_429_after_limit(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("API_KEY", "top-secret")
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "1")
    _write_security_corpus(tmp_path)
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        headers = {"X-API-Key": "top-secret"}
        first = client.post("/v3/chat", headers=headers, json={"message": "黑客攻击"})
        second = client.post("/v3/chat", headers=headers, json={"message": "黑客攻击"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json() == {"detail": "rate limit exceeded"}


def _build_app(tmp_path) -> object:
    semantic_service = StubPhase2SemanticService()
    agent_service = AgentService(data_dir=tmp_path)
    return create_app(
        data_dir=tmp_path,
        semantic_search_service=semantic_service,
        agent_service=agent_service,
    )


def _write_security_corpus(tmp_path) -> None:
    (tmp_path / "sop-005.html").write_text(
        """
        <html>
            <head><title>信息安全 On-Call SOP</title></head>
            <body>
                <h3>场景一：入侵事件响应</h3>
                <p>发现黑客攻击时，先确认攻击类型并启用相应防护。</p>
            </body>
        </html>
        """,
        encoding="utf-8",
    )

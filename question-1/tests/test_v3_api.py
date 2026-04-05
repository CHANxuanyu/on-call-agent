from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.agent_service import AgentService
from app.services.semantic_search_service import SemanticSearchResult


class StubPhase2SemanticService:
    def set_lexical_service(self, lexical_service) -> None:
        del lexical_service

    def load_documents_from_directory(self, directory) -> int:
        del directory
        return 0

    def warmup(self) -> None:
        return None

    def search(self, query: str, *, limit: int = 10) -> list[SemanticSearchResult]:
        del query, limit
        return []


def test_v3_page_and_chat_contract(tmp_path) -> None:
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

    semantic_service = StubPhase2SemanticService()
    agent_service = AgentService(data_dir=tmp_path)
    app = create_app(
        data_dir=tmp_path,
        semantic_search_service=semantic_service,
        agent_service=agent_service,
    )

    with TestClient(app) as client:
        page = client.get("/v3")
        response = client.post("/v3/chat", json={"message": "黑客攻击"})

    assert page.status_code == 200
    assert "Agent SOP Assistant" in page.text
    assert "Conversation History" in page.text
    assert "X-API-Key" in page.text
    assert (tmp_path / "catalog.json").exists()

    payload = response.json()
    assert response.status_code == 200
    assert payload["session_id"]
    assert payload["assistant_message"]
    assert payload["tool_calls"][0]["tool_name"] == "readFile"
    assert payload["tool_calls"][0]["arguments"] == {"fname": "catalog.json"}
    assert payload["consulted_files"] == ["sop-005.html"]
    assert [turn["role"] for turn in payload["history"]] == ["user", "assistant"]
    assert payload["history"][0]["content"] == "黑客攻击"
    assert payload["history"][1]["consulted_files"] == ["sop-005.html"]
    assert payload["history"][1]["tool_calls"][0]["tool_name"] == "readFile"


def test_v3_chat_reuses_session_id(tmp_path) -> None:
    (tmp_path / "sop-008.html").write_text(
        """
        <html>
            <head><title>AI算法 On-Call SOP</title></head>
            <body>
                <h3>场景一：推荐质量下降</h3>
                <p>推荐结果质量下降时，先确认线上特征与排序效果监控状态。</p>
            </body>
        </html>
        """,
        encoding="utf-8",
    )

    semantic_service = StubPhase2SemanticService()
    agent_service = AgentService(data_dir=tmp_path)
    app = create_app(
        data_dir=tmp_path,
        semantic_search_service=semantic_service,
        agent_service=agent_service,
    )

    with TestClient(app) as client:
        first = client.post("/v3/chat", json={"message": "推荐结果质量下降了"})
        session_id = first.json()["session_id"]
        second = client.post("/v3/chat", json={"session_id": session_id, "message": "你刚才看了哪些文件？"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["session_id"] == session_id
    assert [call["arguments"]["fname"] for call in second.json()["tool_calls"]] == ["catalog.json"]
    assert second.json()["consulted_files"] == []
    assert "上次参考 SOP" in second.json()["assistant_message"]
    assert "sop-008.html" in second.json()["assistant_message"]
    assert [turn["role"] for turn in second.json()["history"]] == ["user", "assistant", "user", "assistant"]


def test_v3_history_endpoint_returns_turns_for_existing_session(tmp_path) -> None:
    (tmp_path / "sop-001.html").write_text(
        """
        <html>
            <head><title>后端服务 On-Call SOP</title></head>
            <body>
                <h3>场景一：服务 OOM</h3>
                <p>服务 OOM 时，先检查实例内存使用、最近发布记录和降级开关。</p>
            </body>
        </html>
        """,
        encoding="utf-8",
    )

    app = create_app(
        data_dir=tmp_path,
        semantic_search_service=StubPhase2SemanticService(),
        agent_service=AgentService(data_dir=tmp_path),
    )

    with TestClient(app) as client:
        first = client.post("/v3/chat", json={"message": "服务 OOM 了怎么办？"})
        session_id = first.json()["session_id"]
        history = client.get(f"/v3/history/{session_id}")

    assert history.status_code == 200
    payload = history.json()
    assert payload["session_id"] == session_id
    assert [turn["role"] for turn in payload["history"]] == ["user", "assistant"]
    assert payload["history"][1]["consulted_files"] == ["sop-001.html"]
    assert payload["history"][1]["tool_calls"][0]["arguments"] == {"fname": "catalog.json"}

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.semantic_search_service import SemanticSearchResult


DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class StubPhase2SemanticService:
    def set_lexical_service(self, lexical_service) -> None:
        del lexical_service

    def load_documents_from_directory(self, directory) -> int:
        del directory
        return 1

    def warmup(self) -> None:
        return None

    def search(self, query: str, *, limit: int = 10) -> list[SemanticSearchResult]:
        del query, limit
        return []


def test_healthz_and_readyz_report_service_state(client: TestClient) -> None:
    health_response = client.get("/healthz")
    ready_response = client.get("/readyz")

    assert health_response.status_code == 200
    assert health_response.json()["status"] == "ok"
    assert ready_response.status_code == 200
    assert ready_response.json()["ready"] is True
    assert ready_response.json()["checks"]["startup"]["ready"] is True


def test_request_and_trace_ids_are_echoed_in_response_headers(client: TestClient) -> None:
    response = client.get(
        "/healthz",
        headers={
            "X-Request-ID": "req-observe-123",
            "X-Trace-ID": "trace-observe-456",
        },
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-observe-123"
    assert response.headers["X-Trace-ID"] == "trace-observe-456"


def test_metrics_endpoint_exposes_application_and_runtime_metrics(client: TestClient) -> None:
    client.get("/v1/search", params={"q": "OOM"})

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "oncall_agent_http_requests_total" in response.text
    assert "oncall_agent_http_request_duration_seconds_bucket" in response.text
    assert "oncall_agent_readiness_status" in response.text
    assert "python_info" in response.text or "process_cpu_seconds_total" in response.text


def test_metrics_endpoint_exposes_recommendation_quality_metrics(tmp_path) -> None:
    (tmp_path / "sop-001.html").write_text(
        """
        <html>
            <head><title>后端服务 On-Call SOP</title></head>
            <body>
                <h3>场景一：服务 OOM</h3>
                <p>服务 OOM 时，先检查实例内存使用、最近发布记录和降级开关，再确认是否存在异常流量或大对象缓存。</p>
            </body>
        </html>
        """,
        encoding="utf-8",
    )
    app = create_app(
        data_dir=tmp_path,
        semantic_search_service=StubPhase2SemanticService(),
    )

    with TestClient(app) as client:
        response = client.post("/v3/chat", json={"message": "服务 OOM 了怎么办？"})
        metrics = client.get("/metrics")

    assert response.status_code == 200
    assert "oncall_agent_recommendation_quality_score" in metrics.text
    assert 'dimension="actionability"' in metrics.text
    assert "oncall_agent_recommendation_rewrite_triggers_total" in metrics.text


def test_unhandled_exceptions_are_captured_as_json(tmp_path) -> None:
    (tmp_path / "sop-005.html").write_text(
        """
        <html>
            <head><title>信息安全 On-Call SOP</title></head>
            <body><p>安全事件响应。</p></body>
        </html>
        """,
        encoding="utf-8",
    )
    app = create_app(
        data_dir=tmp_path,
        semantic_search_service=StubPhase2SemanticService(),
    )

    @app.get("/boom")
    def boom() -> dict[str, str]:
        raise RuntimeError("boom")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")
        metrics = client.get("/metrics")

    assert response.status_code == 500
    payload = response.json()
    assert payload["detail"] == "Internal Server Error"
    assert payload["request_id"]
    assert payload["trace_id"]
    assert "oncall_agent_unhandled_exceptions_total" in metrics.text
    assert 'exception_type="RuntimeError"' in metrics.text

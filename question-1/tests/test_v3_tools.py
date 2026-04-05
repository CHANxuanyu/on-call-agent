from __future__ import annotations

import json

import pytest

from app.agent.tools import ReadFileTool, ToolExecutionError, write_catalog


def test_read_file_returns_clean_visible_text_for_html(tmp_path) -> None:
    html_path = tmp_path / "sop-demo.html"
    html_path.write_text(
        """
        <html>
            <head><title>Demo SOP</title><script>const hiddenToken = "leak";</script></head>
            <body>
                <h1>Demo SOP</h1>
                <p>Visible incident handling steps.</p>
            </body>
        </html>
        """,
        encoding="utf-8",
    )

    tool = ReadFileTool(tmp_path)
    result = tool.read_file("sop-demo.html")

    assert "Title: Demo SOP" in result.content
    assert "Visible incident handling steps." in result.content
    assert "hiddenToken" not in result.content


def test_read_file_rejects_path_traversal(tmp_path) -> None:
    tool = ReadFileTool(tmp_path)

    with pytest.raises(ToolExecutionError, match="path traversal"):
        tool.read_file("../secret.txt")


def test_write_catalog_creates_expected_fields(tmp_path) -> None:
    (tmp_path / "sop-001.html").write_text(
        """
        <html>
            <head><title>后端服务 On-Call SOP</title></head>
            <body>
                <p>适用范围：后端服务团队</p>
                <p>处理后端服务故障与超时问题。</p>
                <h3>场景一：服务大面积超时</h3>
                <p>若故障等级为 P0，立即通知值班负责人并启动升级流程。</p>
            </body>
        </html>
        """,
        encoding="utf-8",
    )

    catalog_path = write_catalog(tmp_path)
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))

    assert payload["files"][0]["file_name"] == "sop-001.html"
    assert payload["files"][0]["title"] == "后端服务 On-Call SOP"
    assert payload["files"][0]["team_or_domain"] == "后端服务"
    assert payload["files"][0]["incident_themes"] == ["场景一：服务大面积超时"]
    assert payload["files"][0]["scenario_headings"] == ["场景一：服务大面积超时"]
    assert payload["files"][0]["scenario_snippets"]
    assert "后端服务" in payload["files"][0]["keywords"]
    assert "服务" in payload["files"][0]["operational_terms"]
    assert "p0" in payload["files"][0]["escalation_terms"]
    assert "后端服务故障" in payload["files"][0]["summary"]

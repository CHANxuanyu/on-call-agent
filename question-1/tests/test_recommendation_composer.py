from __future__ import annotations

import json

from app.agent.recommendation import (
    QUALITY_SNAPSHOT_HEADERS,
    RecommendationComposer,
    has_large_verbatim_overlap,
)
from app.agent.tools import ReadFileTool, build_catalog


def _build_composer_inputs(tmp_path, *, file_name: str, html: str) -> tuple[list, dict[str, str]]:
    (tmp_path / file_name).write_text(html, encoding="utf-8")
    catalog_entries = build_catalog(tmp_path)
    payload = ReadFileTool(tmp_path).read_file(file_name).content
    return catalog_entries, {file_name: payload}


def test_recommendation_composer_returns_structured_actionable_output(tmp_path) -> None:
    catalog_entries, consulted_payloads = _build_composer_inputs(
        tmp_path,
        file_name="sop-001.html",
        html="""
        <html>
            <head><title>后端服务 On-Call SOP</title></head>
            <body>
                <h3>场景一：服务 OOM</h3>
                <p>服务 OOM 时，先检查实例内存使用、最近发布记录和降级开关，再确认是否存在异常流量或大对象缓存。</p>
            </body>
        </html>
        """,
    )

    result = RecommendationComposer(mode="rule_based").compose(
        message="服务 OOM 了怎么办？",
        catalog_entries=catalog_entries,
        consulted_payloads=consulted_payloads,
    )

    for header in QUALITY_SNAPSHOT_HEADERS:
        assert header in result.rendered_text
    assert len(result.content.decision_summary) >= 2
    assert len(result.content.action_plan) >= 2
    assert result.quality.actionability_score >= 0.7
    assert result.quality.evidence_coverage_score >= 0.5


def test_recommendation_composer_avoids_large_verbatim_overlap(tmp_path) -> None:
    source_sentence = "服务 OOM 时，先检查实例内存使用、最近发布记录和降级开关，再确认是否存在异常流量或大对象缓存。"
    catalog_entries, consulted_payloads = _build_composer_inputs(
        tmp_path,
        file_name="sop-001.html",
        html=f"""
        <html>
            <head><title>后端服务 On-Call SOP</title></head>
            <body>
                <h3>场景一：服务 OOM</h3>
                <p>{source_sentence}</p>
            </body>
        </html>
        """,
    )

    result = RecommendationComposer(mode="rule_based").compose(
        message="服务 OOM 了怎么办？",
        catalog_entries=catalog_entries,
        consulted_payloads=consulted_payloads,
    )
    evidence_text = list(consulted_payloads.values())

    assert source_sentence not in result.rendered_text
    assert has_large_verbatim_overlap(result.rendered_text, evidence_text) is False
    assert result.quality.duplication_score < 0.4


def test_recommendation_composer_rewrites_copied_llm_output(tmp_path) -> None:
    copied_sentence = "服务 OOM 时，先检查实例内存使用、最近发布记录和降级开关，再确认是否存在异常流量或大对象缓存。"
    catalog_entries, consulted_payloads = _build_composer_inputs(
        tmp_path,
        file_name="sop-001.html",
        html=f"""
        <html>
            <head><title>后端服务 On-Call SOP</title></head>
            <body>
                <h3>场景一：服务 OOM</h3>
                <p>{copied_sentence}</p>
            </body>
        </html>
        """,
    )
    llm_payload = {
        "decision_summary": [copied_sentence],
        "action_plan": [copied_sentence],
        "priority_and_severity_rationale": "该问题会影响服务可用性。",
        "risks_and_side_effects": ["直接重启可能掩盖现场。"],
        "rollback_and_mitigation": ["必要时准备回滚或降级。"],
        "escalation_conditions": ["如果影响面扩大，请立即升级。"],
        "confidence_and_missing_information": "置信度：中。还缺少实例内存曲线和最近发布记录。",
        "supporting_evidence": [
            {
                "file": "sop-001.html",
                "title": "后端服务 On-Call SOP",
                "reason": copied_sentence,
            }
        ],
    }
    raw_output = (
        "JSON:\n"
        f"{json.dumps(llm_payload, ensure_ascii=False, indent=2)}\n"
        "TEXT:\n"
        "建议处理方式\n"
        f"- {copied_sentence}\n"
    )

    result = RecommendationComposer(mode="llm").finalize_llm_output(
        raw_output=raw_output,
        consulted_payloads=consulted_payloads,
        consulted_files=["sop-001.html"],
    )

    assert result.quality.rewrite_triggered is True
    assert "行动计划" in result.rendered_text
    assert has_large_verbatim_overlap(result.rendered_text, list(consulted_payloads.values())) is False

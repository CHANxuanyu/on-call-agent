from __future__ import annotations

from pathlib import Path

from app.agent.tools import ReadFileTool, ToolExecutionError
from app.services.agent_service import AgentService


def _assert_structured_recommendation(text: str) -> None:
    for marker in (
        "建议处理方式",
        "结论",
        "行动计划",
        "优先级与判断依据",
        "风险与副作用",
        "回滚/缓解",
        "升级条件",
        "置信度与缺失信息",
        "支持依据",
        "参考 SOP",
    ):
        assert marker in text
    assert "1. " in text


def _successful_read_filenames(result) -> list[str]:
    return [
        call.arguments["fname"]
        for call in result.tool_calls
        if call.tool_name == "readFile" and call.status == "ok"
    ]


def _successful_sop_reads(result) -> list[str]:
    return [fname for fname in _successful_read_filenames(result) if fname != "catalog.json"]


def _write_phase3_corpus(data_dir: Path) -> None:
    (data_dir / "sop-001.html").write_text(
        """
        <html>
            <head><title>后端服务 On-Call SOP</title></head>
            <body>
                <p>后端服务团队负责核心应用服务的稳定性。</p>
                <h3>场景一：服务 OOM</h3>
                <p>服务 OOM 时，先检查实例内存使用、最近发布记录和降级开关，再确认是否存在异常流量或大对象缓存。</p>
                <h3>场景二：P0 故障响应流程</h3>
                <p>若故障等级为 P0，先通知业务负责人，拉起 war room，并准备回滚或降级方案。</p>
            </body>
        </html>
        """,
        encoding="utf-8",
    )
    (data_dir / "sop-002.html").write_text(
        """
        <html>
            <head><title>数据库 DBA On-Call SOP</title></head>
            <body>
                <p>数据库 DBA 值班工程师负责保障核心数据库可用性。</p>
                <h3>场景一：主从复制延迟</h3>
                <p>当数据库主从延迟超过30秒时，先检查复制线程状态、binlog 积压情况和从库负载，再确认是否存在慢查询或大事务阻塞复制。</p>
            </body>
        </html>
        """,
        encoding="utf-8",
    )
    (data_dir / "sop-004.html").write_text(
        """
        <html>
            <head><title>SRE基础设施 On-Call SOP</title></head>
            <body>
                <p>SRE 团队负责基础设施与集群稳定性。</p>
                <h3>场景一：Kubernetes 集群故障</h3>
                <p>集群层面故障时，先检查节点、Ingress 和核心监控告警。</p>
                <h3>场景二：P0 故障响应流程</h3>
                <p>P0 故障时，需要协调后端、DBA 和安全团队，统一跟踪恢复进度并更新通知。</p>
            </body>
        </html>
        """,
        encoding="utf-8",
    )
    (data_dir / "sop-005.html").write_text(
        """
        <html>
            <head><title>信息安全 On-Call SOP</title></head>
            <body>
                <p>安全团队负责处理安全事件与入侵风险。</p>
                <h3>场景一：入侵事件响应</h3>
                <p>怀疑系统被入侵时，立即隔离主机，保全证据，轮换高风险凭证，并上报安全事件。</p>
            </body>
        </html>
        """,
        encoding="utf-8",
    )
    (data_dir / "sop-008.html").write_text(
        """
        <html>
            <head><title>AI算法 On-Call SOP</title></head>
            <body>
                <p>AI 算法团队负责模型推理与推荐效果稳定性。</p>
                <h3>场景一：推荐质量下降</h3>
                <p>推荐结果质量下降时，先检查特征新鲜度、模型版本、排序效果监控和线上实验配置。</p>
            </body>
        </html>
        """,
        encoding="utf-8",
    )


class RejectingReadFileTool(ReadFileTool):
    def __init__(self, data_dir: Path, *, rejected_files: set[str]) -> None:
        super().__init__(data_dir)
        self._rejected_files = set(rejected_files)

    def read_file(self, fname: str):
        if fname in self._rejected_files:
            raise ToolExecutionError(f"simulated rejection: {fname}")
        return super().read_file(fname)


def test_agent_reads_catalog_first_then_routes_with_catalog_only(tmp_path) -> None:
    _write_phase3_corpus(tmp_path)
    service = AgentService(data_dir=tmp_path)
    service.ensure_catalog()

    result = service.chat(session_id=None, message="服务 OOM 了怎么办？")

    assert result.tool_calls[0].arguments == {"fname": "catalog.json"}
    assert _successful_read_filenames(result) == ["catalog.json", "sop-001.html"]
    assert result.consulted_files == _successful_sop_reads(result) == ["sop-001.html"]
    _assert_structured_recommendation(result.assistant_message)
    assert "实例内存" in result.assistant_message
    assert "sop-001.html" in result.assistant_message


def test_agent_routes_replication_delay_to_dba_sop(tmp_path) -> None:
    _write_phase3_corpus(tmp_path)
    service = AgentService(data_dir=tmp_path)
    service.ensure_catalog()

    result = service.chat(session_id=None, message="数据库主从延迟超过30秒怎么处理？")

    assert result.consulted_files == _successful_sop_reads(result) == ["sop-002.html"]
    _assert_structured_recommendation(result.assistant_message)
    assert "复制线程" in result.assistant_message
    assert "binlog 积压" in result.assistant_message


def test_agent_prefers_relevant_scenario_paragraph_over_generic_intro(tmp_path) -> None:
    _write_phase3_corpus(tmp_path)
    service = AgentService(data_dir=tmp_path)
    service.ensure_catalog()

    result = service.chat(session_id=None, message="数据库主从延迟超过30秒怎么处理？")

    assert result.consulted_files == _successful_sop_reads(result) == ["sop-002.html"]
    assert "数据库 DBA 值班工程师负责保障核心数据库可用性" not in result.assistant_message
    assert "复制线程" in result.assistant_message


def test_agent_prefers_scenario_action_content_over_boilerplate_section(tmp_path) -> None:
    (tmp_path / "sop-001.html").write_text(
        """
        <html>
            <head><title>后端服务 On-Call SOP</title></head>
            <body>
                <p>后端服务团队负责核心应用服务的稳定性。</p>
                <p>一、值班职责 值班工程师负责巡检、交接和日常响应。</p>
                <h3>场景一：服务 OOM</h3>
                <p>服务 OOM 时，先检查实例内存使用、最近发布记录和降级开关，再确认是否存在异常流量或大对象缓存。</p>
            </body>
        </html>
        """,
        encoding="utf-8",
    )
    service = AgentService(data_dir=tmp_path)
    service.ensure_catalog()

    result = service.chat(session_id=None, message="服务 OOM 了怎么办？")

    assert _successful_read_filenames(result) == ["catalog.json", "sop-001.html"]
    assert result.consulted_files == _successful_sop_reads(result) == ["sop-001.html"]
    _assert_structured_recommendation(result.assistant_message)
    assert "实例内存" in result.assistant_message
    assert "一、值班职责" not in result.assistant_message
    assert "负责巡检、交接和日常响应" not in result.assistant_message


def test_agent_prefers_inline_remediation_steps_over_mixed_intro_blob(tmp_path) -> None:
    (tmp_path / "sop-001.html").write_text(
        """
        <html>
            <head><title>后端服务 On-Call SOP</title></head>
            <body>
                <p>后端服务团队负责线上稳定性和值班协作。</p>
                <h3>场景一：P0 故障响应流程</h3>
                <p>处理步骤：1. 5分钟内拉起 war room 2. 通知业务负责人并冻结变更 3. 准备回滚或降级方案</p>
            </body>
        </html>
        """,
        encoding="utf-8",
    )
    service = AgentService(data_dir=tmp_path)
    service.ensure_catalog()

    result = service.chat(session_id=None, message="P0 故障的响应流程是什么？")

    assert _successful_read_filenames(result) == ["catalog.json", "sop-001.html"]
    assert result.consulted_files == _successful_sop_reads(result) == ["sop-001.html"]
    assert "5分钟内拉起 war room" in result.assistant_message
    assert "冻结变更" in result.assistant_message
    assert "后端服务团队负责线上稳定性和值班协作" not in result.assistant_message


def test_agent_prefers_threshold_triggered_escalation_over_generic_remediation(tmp_path) -> None:
    (tmp_path / "sop-001.html").write_text(
        """
        <html>
            <head><title>后端服务 On-Call SOP</title></head>
            <body>
                <p>后端服务团队负责接口稳定性。</p>
                <h3>场景一：接口错误率升高</h3>
                <p>先检查最近发布、依赖超时和熔断状态。</p>
                <p>如果错误率持续5分钟高于5%，立即升级为 P1，通知值班负责人并拉起 war room。</p>
            </body>
        </html>
        """,
        encoding="utf-8",
    )
    service = AgentService(data_dir=tmp_path)
    service.ensure_catalog()

    result = service.chat(session_id=None, message="错误率持续5分钟高于5%时要不要升级？")

    assert _successful_read_filenames(result) == ["catalog.json", "sop-001.html"]
    assert result.consulted_files == _successful_sop_reads(result) == ["sop-001.html"]
    assert "错误率持续5分钟高于5%" in result.assistant_message
    assert "升级为 P1" in result.assistant_message
    assert "拉起 war room" in result.assistant_message
    assert "先检查最近发布、依赖超时和熔断状态" not in result.assistant_message


def test_agent_prefers_oom_specific_guidance_over_generic_backend_remediation(tmp_path) -> None:
    (tmp_path / "sop-001.html").write_text(
        """
        <html>
            <head><title>后端服务 On-Call SOP</title></head>
            <body>
                <p>后端服务团队负责核心服务稳定性。</p>
                <h3>场景一：服务异常</h3>
                <p>先检查最近发布、依赖超时和降级开关。</p>
                <p>如果出现 OOM 或 RSS 持续增长，先导出堆快照，检查大对象缓存和异常流量，再确认是否需要重启实例。</p>
            </body>
        </html>
        """,
        encoding="utf-8",
    )
    service = AgentService(data_dir=tmp_path)
    service.ensure_catalog()

    result = service.chat(session_id=None, message="服务 OOM 了怎么办？")

    assert _successful_read_filenames(result) == ["catalog.json", "sop-001.html"]
    assert result.consulted_files == _successful_sop_reads(result) == ["sop-001.html"]
    assert "OOM" in result.assistant_message
    assert "RSS 持续增长" in result.assistant_message
    assert "导出堆快照" in result.assistant_message
    assert "大对象缓存" in result.assistant_message
    assert "先检查最近发布、依赖超时和降级开关" not in result.assistant_message


def test_agent_routes_intrusion_query_to_security_sop(tmp_path) -> None:
    _write_phase3_corpus(tmp_path)
    service = AgentService(data_dir=tmp_path)
    service.ensure_catalog()

    result = service.chat(session_id=None, message="怀疑有人入侵了系统")

    assert result.consulted_files == _successful_sop_reads(result) == ["sop-005.html"]
    assert "隔离主机" in result.assistant_message
    assert "保留证据" in result.assistant_message or "保全证据" in result.assistant_message


def test_agent_routes_recommendation_quality_drop_to_ai_sop(tmp_path) -> None:
    _write_phase3_corpus(tmp_path)
    service = AgentService(data_dir=tmp_path)
    service.ensure_catalog()

    result = service.chat(session_id=None, message="推荐结果质量下降了")

    assert result.consulted_files == _successful_sop_reads(result) == ["sop-008.html"]
    _assert_structured_recommendation(result.assistant_message)
    assert "特征时效" in result.assistant_message or "特征新鲜度" in result.assistant_message
    assert "排序监控" in result.assistant_message or "排序效果监控" in result.assistant_message


def test_agent_reads_multiple_sops_for_p0_flow_question(tmp_path) -> None:
    _write_phase3_corpus(tmp_path)
    service = AgentService(data_dir=tmp_path)
    service.ensure_catalog()

    result = service.chat(session_id=None, message="P0 故障的响应流程是什么？")

    assert result.tool_calls[0].arguments == {"fname": "catalog.json"}
    assert _successful_read_filenames(result) == ["catalog.json", "sop-001.html", "sop-004.html"]
    assert result.consulted_files == _successful_sop_reads(result) == ["sop-001.html", "sop-004.html"]
    assert "war room" in result.assistant_message
    assert "协调后端、DBA 和安全团队" in result.assistant_message


def test_agent_routes_related_unseen_query_via_catalog_terms(tmp_path) -> None:
    _write_phase3_corpus(tmp_path)
    service = AgentService(data_dir=tmp_path)
    service.ensure_catalog()

    result = service.chat(session_id=None, message="从库复制卡住了，先看什么？")

    assert result.consulted_files == _successful_sop_reads(result) == ["sop-002.html"]
    assert "复制线程状态" in result.assistant_message


def test_agent_answers_conservatively_when_catalog_signal_is_weak(tmp_path) -> None:
    _write_phase3_corpus(tmp_path)
    service = AgentService(data_dir=tmp_path)
    service.ensure_catalog()

    result = service.chat(session_id=None, message="线上有点问题，先看哪里？")

    assert result.tool_calls[0].arguments == {"fname": "catalog.json"}
    assert _successful_read_filenames(result) == ["catalog.json"]
    assert result.consulted_files == _successful_sop_reads(result) == []
    assert "还不够明确" in result.assistant_message
    assert "请补充是数据库、后端、基础设施、安全，还是 AI/推荐相关问题" in result.assistant_message


def test_agent_uses_recent_history_for_follow_up_file_question(tmp_path) -> None:
    _write_phase3_corpus(tmp_path)
    service = AgentService(data_dir=tmp_path)
    service.ensure_catalog()

    first = service.chat(session_id=None, message="服务 OOM 了怎么办？")
    second = service.chat(session_id=first.session_id, message="你刚才看了哪些文件？")

    assert second.tool_calls[0].arguments == {"fname": "catalog.json"}
    assert _successful_read_filenames(second) == ["catalog.json"]
    assert second.consulted_files == _successful_sop_reads(second) == []
    assert "上次参考 SOP" in second.assistant_message
    assert "sop-001.html" in second.assistant_message


def test_agent_keeps_failed_sop_reads_out_of_consulted_files(tmp_path) -> None:
    _write_phase3_corpus(tmp_path)
    tool = RejectingReadFileTool(tmp_path, rejected_files={"sop-001.html"})
    service = AgentService(data_dir=tmp_path, read_file_tool=tool)
    service.ensure_catalog()

    result = service.chat(session_id=None, message="服务 OOM 了怎么办？")

    assert [call.arguments["fname"] for call in result.tool_calls] == ["catalog.json", "sop-001.html"]
    assert [call.status for call in result.tool_calls] == ["ok", "error"]
    assert result.consulted_files == _successful_sop_reads(result) == []
    assert "当前轮次只读取了 `catalog.json`" in result.assistant_message

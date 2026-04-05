from __future__ import annotations

import json
from types import SimpleNamespace

from app.agent.llm_loop import LLMAgentLoop
from app.agent.loop import AgentLoop
from app.agent.memory import ConversationTurn
from app.agent.tools import ReadFileTool, write_catalog
from app.services import agent_service as agent_service_module
from app.services.agent_service import AgentService


def _write_llm_corpus(tmp_path) -> None:
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


def _tool_call(call_id: str, *, fname: str, tool_name: str = "read_file") -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=tool_name, arguments=json.dumps({"fname": fname}, ensure_ascii=False)),
    )


def _response(*, content: str | None = None, tool_calls: list[SimpleNamespace] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=content,
                    tool_calls=tool_calls,
                )
            )
        ]
    )


class StubChatCompletions:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class StubOpenAIClient:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self.chat = SimpleNamespace(completions=StubChatCompletions(responses))


def test_llm_loop_executes_read_file_tool_calls(monkeypatch, tmp_path) -> None:
    _write_llm_corpus(tmp_path)
    write_catalog(tmp_path)

    stub_client = StubOpenAIClient(
        [
            _response(tool_calls=[_tool_call("call_1", fname="catalog.json")]),
            _response(tool_calls=[_tool_call("call_2", fname="sop-001.html")]),
            _response(
                content=(
                    "建议处理方式\n"
                    "- 服务 OOM 时，先检查实例内存使用、最近发布记录和降级开关。\n\n"
                    "参考 SOP\n"
                    "- `sop-001.html`"
                )
            ),
        ]
    )
    monkeypatch.setattr(
        "app.agent.llm_loop.openai",
        SimpleNamespace(OpenAI=lambda: stub_client),
    )

    loop = LLMAgentLoop(read_file_tool=ReadFileTool(tmp_path))
    result = loop.run(
        "服务 OOM 了怎么办？",
        history=[ConversationTurn(role="user", content="服务 OOM 了怎么办？")],
    )

    assert [call.arguments["fname"] for call in result.tool_calls] == ["catalog.json", "sop-001.html"]
    assert [call.status for call in result.tool_calls] == ["ok", "ok"]
    assert result.consulted_files == ["sop-001.html"]
    assert "服务 OOM 时" in result.assistant_message
    first_request_messages = stub_client.chat.completions.calls[0]["messages"]
    assert [message["content"] for message in first_request_messages if message["role"] == "user"] == [
        "服务 OOM 了怎么办？"
    ]


def test_agent_service_uses_rule_based_loop_without_api_key(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    service = AgentService(data_dir=tmp_path)

    assert isinstance(service._loop, AgentLoop)


def test_agent_service_uses_llm_loop_with_api_key(monkeypatch, tmp_path) -> None:
    class StubLLMLoop:
        def __init__(self, *, read_file_tool) -> None:
            self.read_file_tool = read_file_tool

        def run(self, message: str, *, history=None):
            del message, history
            raise AssertionError("run should not be called in this constructor test")

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(agent_service_module, "LLMAgentLoop", StubLLMLoop)

    service = AgentService(data_dir=tmp_path)

    assert isinstance(service._loop, StubLLMLoop)


def test_agent_service_falls_back_when_llm_loop_init_fails(monkeypatch, tmp_path) -> None:
    class FailingLLMLoop:
        def __init__(self, *, read_file_tool) -> None:
            del read_file_tool
            raise RuntimeError("missing openai")

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(agent_service_module, "LLMAgentLoop", FailingLLMLoop)

    service = AgentService(data_dir=tmp_path)

    assert isinstance(service._loop, AgentLoop)

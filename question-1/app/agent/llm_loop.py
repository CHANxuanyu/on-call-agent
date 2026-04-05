from __future__ import annotations

import json
import logging
import os
from typing import Any

try:
    import openai
except ImportError:  # pragma: no cover - exercised in environments without the SDK installed
    openai = None  # type: ignore[assignment]

from app.agent.loop import AgentRunResult, RECOMMENDATION_FEATURE_ENV
from app.agent.memory import ConversationTurn
from app.agent.prompting import build_system_prompt
from app.agent.recommendation import RecommendationComposer
from app.agent.tools import CATALOG_FILE_NAME, ReadFileTool, ToolCallRecord, ToolExecutionError
from app.observability.metrics import observe_dependency


DEFAULT_MODEL = "gpt-4o-mini"
OPENAI_TOOL_NAME = "read_file"
TOOL_RECORD_NAME = "readFile"
MAX_TOOL_ROUNDS = 8
logger = logging.getLogger(__name__)


class LLMAgentLoop:
    def __init__(
        self,
        *,
        read_file_tool: ReadFileTool,
        model: str = DEFAULT_MODEL,
    ) -> None:
        if openai is None:
            raise RuntimeError("The openai package is required to use LLMAgentLoop")

        self._read_file_tool = read_file_tool
        self._model = model
        self._system_prompt = build_system_prompt()
        self._client = openai.OpenAI()
        self._recommendation_enabled = _env_flag_enabled(RECOMMENDATION_FEATURE_ENV, default=True)
        self._recommendation_composer = RecommendationComposer(mode="llm")
        self._tools: list[dict[str, object]] = [
            {
                "type": "function",
                "function": {
                    "name": OPENAI_TOOL_NAME,
                    "description": (
                        "Reads an SOP file from the catalog by its filename. "
                        "Use 'catalog.json' to see available files."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "fname": {
                                "type": "string",
                                "description": "The filename to read, such as 'catalog.json' or 'sop-001.html'.",
                            }
                        },
                        "required": ["fname"],
                    },
                },
            }
        ]

    def run(self, message: str, *, history: list[ConversationTurn] | None = None) -> AgentRunResult:
        messages = self._build_messages(message, history or [])
        tool_call_records: list[ToolCallRecord] = []
        consulted_files: list[str] = []
        consulted_payloads: dict[str, str] = {}
        seen_consulted_files: set[str] = set()

        for _ in range(MAX_TOOL_ROUNDS):
            with observe_dependency("openai", "chat_completions"):
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    tools=self._tools,
                    tool_choice="auto",
                )
            response_message = response.choices[0].message
            tool_calls = list(response_message.tool_calls or [])
            logger.info(
                "llm_response_received",
                extra={
                    "event": "llm_response_received",
                    "dependency": "openai",
                    "operation": "chat_completions",
                    "model": self._model,
                    "tool_call_count": len(tool_calls),
                    "openai_request_id": getattr(response, "_request_id", None),
                },
            )

            if not tool_calls:
                assistant_message = response_message.content or (
                    "I could not produce a grounded answer yet."
                )
                if self._recommendation_enabled and consulted_payloads:
                    try:
                        recommendation = self._recommendation_composer.finalize_llm_output(
                            raw_output=assistant_message,
                            consulted_payloads=consulted_payloads,
                            consulted_files=consulted_files,
                        )
                        assistant_message = recommendation.rendered_text
                    except Exception:
                        logger.exception(
                            "llm_recommendation_finalize_failed",
                            extra={
                                "event": "llm_recommendation_finalize_failed",
                                "model": self._model,
                            },
                        )
                return AgentRunResult(
                    assistant_message=assistant_message,
                    tool_calls=tool_call_records,
                    consulted_files=consulted_files,
                )

            messages.append(self._assistant_message_to_dict(response_message, tool_calls))

            for tool_call in tool_calls:
                tool_output = self._execute_tool_call(
                    tool_call=tool_call,
                    tool_call_records=tool_call_records,
                    consulted_files=consulted_files,
                    consulted_payloads=consulted_payloads,
                    seen_consulted_files=seen_consulted_files,
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_output,
                    }
                )

        return AgentRunResult(
            assistant_message=(
                "I could not finish the tool loop safely within the allowed number of steps."
            ),
            tool_calls=tool_call_records,
            consulted_files=consulted_files,
        )

    def _build_messages(
        self,
        message: str,
        history: list[ConversationTurn],
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": self._system_prompt}]

        for turn in history:
            if turn.role not in {"user", "assistant", "system"}:
                continue
            if not turn.content:
                continue
            messages.append({"role": turn.role, "content": turn.content})

        if not history or history[-1].role != "user" or history[-1].content != message:
            messages.append({"role": "user", "content": message})

        return messages

    def _assistant_message_to_dict(
        self,
        response_message: Any,
        tool_calls: list[Any],
    ) -> dict[str, Any]:
        message: dict[str, Any] = {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments,
                    },
                }
                for tool_call in tool_calls
            ],
        }
        if response_message.content is not None:
            message["content"] = response_message.content
        return message

    def _execute_tool_call(
        self,
        *,
        tool_call: Any,
        tool_call_records: list[ToolCallRecord],
        consulted_files: list[str],
        consulted_payloads: dict[str, str],
        seen_consulted_files: set[str],
    ) -> str:
        tool_name = getattr(tool_call.function, "name", "")
        raw_arguments = getattr(tool_call.function, "arguments", "") or "{}"

        if tool_name != OPENAI_TOOL_NAME:
            error_message = f"Unsupported tool requested: {tool_name}"
            tool_call_records.append(
                ToolCallRecord(
                    tool_name=tool_name or TOOL_RECORD_NAME,
                    arguments={},
                    status="error",
                    output_preview=error_message,
                )
            )
            return error_message

        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            error_message = f"Invalid tool arguments: {exc}"
            tool_call_records.append(
                ToolCallRecord(
                    tool_name=TOOL_RECORD_NAME,
                    arguments={},
                    status="error",
                    output_preview=error_message,
                )
            )
            return error_message

        fname = arguments.get("fname")
        if not isinstance(fname, str) or not fname.strip():
            error_message = "The read_file tool requires a non-empty string 'fname' argument."
            tool_call_records.append(
                ToolCallRecord(
                    tool_name=TOOL_RECORD_NAME,
                    arguments={"fname": str(fname)},
                    status="error",
                    output_preview=error_message,
                )
            )
            return error_message

        resolved_fname = fname.strip()
        logger.info(
            "agent_tool_invocation",
            extra={
                "event": "agent_tool_invocation",
                "tool_name": TOOL_RECORD_NAME,
                "fname": resolved_fname,
            },
        )

        try:
            result = self._read_file_tool.read_file(resolved_fname)
        except ToolExecutionError as exc:
            tool_call_records.append(
                ToolCallRecord(
                    tool_name=TOOL_RECORD_NAME,
                    arguments={"fname": resolved_fname},
                    status="error",
                    output_preview=str(exc),
                )
            )
            return str(exc)

        tool_call_records.append(
            ToolCallRecord(
                tool_name=TOOL_RECORD_NAME,
                arguments={"fname": resolved_fname},
                status="ok",
                output_preview=result.preview,
            )
        )
        if result.fname != CATALOG_FILE_NAME:
            consulted_payloads.setdefault(result.fname, result.content)
            if result.fname not in seen_consulted_files:
                seen_consulted_files.add(result.fname)
                consulted_files.append(result.fname)
        return result.content


def _env_flag_enabled(name: str, *, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().casefold() not in {"0", "false", "off", "no"}

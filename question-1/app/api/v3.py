from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse

from app.core.schemas import ChatHistoryTurn, ChatRequest, ChatResponse, SessionHistoryResponse, ToolTrace
from app.security import enforce_v3_chat_rate_limit, require_api_key
from app.services.agent_service import AgentConversationTurn, AgentService


router = APIRouter(prefix="/v3", tags=["phase-3"])


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    request: Request,
    _: None = Depends(require_api_key),
    __: None = Depends(enforce_v3_chat_rate_limit),
) -> ChatResponse:
    service = _get_agent_service(request)
    result = service.chat(session_id=payload.session_id, message=payload.message)
    return ChatResponse(
        session_id=result.session_id,
        assistant_message=result.assistant_message,
        tool_calls=_to_tool_traces(result.tool_calls),
        consulted_files=result.consulted_files,
        history=_to_chat_history(result.history),
    )


@router.get("/history/{session_id}", response_model=SessionHistoryResponse)
def history(
    session_id: str,
    request: Request,
    _: None = Depends(require_api_key),
) -> SessionHistoryResponse:
    service = _get_agent_service(request)
    turns = service.get_history(session_id=session_id)
    if turns is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="session not found",
        )
    return SessionHistoryResponse(
        session_id=session_id,
        history=_to_chat_history(turns),
    )


@router.get("", response_class=HTMLResponse, include_in_schema=False)
def chat_page(request: Request) -> HTMLResponse:
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="v3.html",
        context={},
    )


def _get_agent_service(request: Request) -> AgentService:
    return request.app.state.agent_service


def _to_tool_traces(tool_calls) -> list[ToolTrace]:
    return [
        ToolTrace(
            tool_name=call.tool_name,
            arguments=call.arguments,
            status=call.status,
            output_preview=call.output_preview,
        )
        for call in tool_calls
    ]


def _to_chat_history(turns: list[AgentConversationTurn]) -> list[ChatHistoryTurn]:
    return [
        ChatHistoryTurn(
            role=turn.role,
            content=turn.content,
            consulted_files=turn.consulted_files,
            tool_calls=_to_tool_traces(turn.tool_calls),
        )
        for turn in turns
    ]

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
import uuid


REQUEST_ID_HEADER = "X-Request-ID"
TRACE_ID_HEADER = "X-Trace-ID"
_REQUEST_ID = ContextVar("request_id", default="-")
_TRACE_ID = ContextVar("trace_id", default="-")


@dataclass(frozen=True, slots=True)
class BoundRequestContext:
    request_id_token: Token[str]
    trace_id_token: Token[str]


def current_request_id() -> str:
    return _REQUEST_ID.get()


def current_trace_id() -> str:
    return _TRACE_ID.get()


def generate_request_id() -> str:
    return uuid.uuid4().hex


def generate_trace_id() -> str:
    return uuid.uuid4().hex


def bind_request_context(request_id: str, trace_id: str) -> BoundRequestContext:
    return BoundRequestContext(
        request_id_token=_REQUEST_ID.set(request_id),
        trace_id_token=_TRACE_ID.set(trace_id),
    )


def reset_request_context(context: BoundRequestContext) -> None:
    _REQUEST_ID.reset(context.request_id_token)
    _TRACE_ID.reset(context.trace_id_token)

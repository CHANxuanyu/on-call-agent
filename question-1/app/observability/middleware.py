from __future__ import annotations

import logging
from time import perf_counter

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.observability.context import (
    REQUEST_ID_HEADER,
    TRACE_ID_HEADER,
    bind_request_context,
    generate_request_id,
    generate_trace_id,
    reset_request_context,
)
from app.observability.metrics import (
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUEST_ERRORS_TOTAL,
    HTTP_REQUESTS_TOTAL,
    UNHANDLED_EXCEPTIONS_TOTAL,
)


logger = logging.getLogger(__name__)


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or generate_request_id()
        trace_id = request.headers.get(TRACE_ID_HEADER) or request_id or generate_trace_id()
        request.state.request_id = request_id
        request.state.trace_id = trace_id
        bound_context = bind_request_context(request_id=request_id, trace_id=trace_id)
        started_at = perf_counter()
        response: Response | None = None
        caught_exception: Exception | None = None

        try:
            response = await call_next(request)
            return response
        except Exception as exc:
            caught_exception = exc
            logger.exception(
                "unhandled_exception",
                extra={
                    "event": "unhandled_exception",
                    "method": request.method,
                    "path": request.url.path,
                    "client_ip": request.client.host if request.client is not None else None,
                },
            )
            response = JSONResponse(
                status_code=500,
                content={
                    "detail": "Internal Server Error",
                    "request_id": request_id,
                    "trace_id": trace_id,
                },
            )
            return response
        finally:
            route = _route_label(request)
            status_code = response.status_code if response is not None else 500
            duration_seconds = perf_counter() - started_at

            if response is not None:
                response.headers[REQUEST_ID_HEADER] = request_id
                response.headers[TRACE_ID_HEADER] = trace_id

            HTTP_REQUESTS_TOTAL.labels(
                method=request.method,
                route=route,
                status_code=str(status_code),
            ).inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(
                method=request.method,
                route=route,
                status_code=str(status_code),
            ).observe(duration_seconds)

            if status_code >= 400:
                HTTP_REQUEST_ERRORS_TOTAL.labels(
                    method=request.method,
                    route=route,
                    status_code=str(status_code),
                ).inc()
            if caught_exception is not None:
                UNHANDLED_EXCEPTIONS_TOTAL.labels(
                    route=route,
                    exception_type=type(caught_exception).__name__,
                ).inc()

            logger.info(
                "request_completed",
                extra={
                    "event": "request_completed",
                    "method": request.method,
                    "route": route,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": round(duration_seconds * 1000, 3),
                    "client_ip": request.client.host if request.client is not None else None,
                },
            )
            reset_request_context(bound_context)


def _route_label(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if isinstance(route_path, str):
        return route_path
    return request.url.path

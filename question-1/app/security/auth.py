from __future__ import annotations

import logging
import secrets

from fastapi import HTTPException, Request, status

from app.security.config import API_KEY_HEADER, SecuritySettings


logger = logging.getLogger(__name__)


def require_api_key(request: Request) -> None:
    settings = _security_settings(request)
    if not settings.auth_enabled:
        return

    provided_api_key = request.headers.get(API_KEY_HEADER)
    if provided_api_key and secrets.compare_digest(provided_api_key, settings.api_key or ""):
        return

    logger.warning(
        "api_key_auth_failed",
        extra={
            "event": "api_key_auth_failed",
            "path": request.url.path,
            "client_ip": _client_ip(request),
            "reason": "missing" if not provided_api_key else "invalid",
        },
    )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="unauthorized",
    )


def _security_settings(request: Request) -> SecuritySettings:
    return request.app.state.security_settings


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client is not None else None

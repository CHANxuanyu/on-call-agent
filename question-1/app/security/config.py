from __future__ import annotations

from dataclasses import dataclass
import logging
import os


API_KEY_ENV = "API_KEY"
RATE_LIMIT_PER_MIN_ENV = "RATE_LIMIT_PER_MIN"
API_KEY_HEADER = "X-API-Key"
DEFAULT_RATE_LIMIT_PER_MIN = 30
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SecuritySettings:
    api_key: str | None
    rate_limit_per_min: int = DEFAULT_RATE_LIMIT_PER_MIN

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_key)


def load_security_settings() -> SecuritySettings:
    raw_api_key = os.getenv(API_KEY_ENV)
    api_key = raw_api_key.strip() if raw_api_key and raw_api_key.strip() else None
    rate_limit_per_min = _resolve_rate_limit_per_min(os.getenv(RATE_LIMIT_PER_MIN_ENV))
    return SecuritySettings(api_key=api_key, rate_limit_per_min=rate_limit_per_min)


def log_security_startup(settings: SecuritySettings) -> None:
    if not settings.auth_enabled:
        logger.warning(
            "api_key_not_configured_auth_disabled",
            extra={
                "event": "api_key_not_configured_auth_disabled",
                "auth_enabled": False,
                "header_name": API_KEY_HEADER,
                "rate_limit_per_min": settings.rate_limit_per_min,
                "message_hint": "Set API_KEY in production to enforce authentication.",
            },
        )
        return

    logger.info(
        "api_key_configured",
        extra={
            "event": "api_key_configured",
            "auth_enabled": True,
            "header_name": API_KEY_HEADER,
            "rate_limit_per_min": settings.rate_limit_per_min,
        },
    )


def _resolve_rate_limit_per_min(raw_value: str | None) -> int:
    if raw_value is None or not raw_value.strip():
        return DEFAULT_RATE_LIMIT_PER_MIN

    try:
        rate_limit_per_min = int(raw_value)
    except ValueError:
        _log_invalid_rate_limit(raw_value)
        return DEFAULT_RATE_LIMIT_PER_MIN

    if rate_limit_per_min <= 0:
        _log_invalid_rate_limit(raw_value)
        return DEFAULT_RATE_LIMIT_PER_MIN

    return rate_limit_per_min


def _log_invalid_rate_limit(raw_value: str) -> None:
    logger.warning(
        "rate_limit_config_invalid",
        extra={
            "event": "rate_limit_config_invalid",
            "env_var": RATE_LIMIT_PER_MIN_ENV,
            "value": raw_value,
            "fallback": DEFAULT_RATE_LIMIT_PER_MIN,
        },
    )

from __future__ import annotations

from contextlib import contextmanager
from time import perf_counter
from typing import TYPE_CHECKING, Iterator

from fastapi import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

if TYPE_CHECKING:
    from app.agent.recommendation import RecommendationQuality


HTTP_REQUESTS_TOTAL = Counter(
    "oncall_agent_http_requests_total",
    "Total HTTP requests processed by the application.",
    ["method", "route", "status_code"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "oncall_agent_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "route", "status_code"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
HTTP_REQUEST_ERRORS_TOTAL = Counter(
    "oncall_agent_http_request_errors_total",
    "HTTP requests that resulted in error responses.",
    ["method", "route", "status_code"],
)
UNHANDLED_EXCEPTIONS_TOTAL = Counter(
    "oncall_agent_unhandled_exceptions_total",
    "Unhandled exceptions caught by the application middleware.",
    ["route", "exception_type"],
)
DEPENDENCY_REQUESTS_TOTAL = Counter(
    "oncall_agent_dependency_requests_total",
    "Dependency calls made by the application.",
    ["dependency", "operation", "status"],
)
DEPENDENCY_REQUEST_DURATION_SECONDS = Histogram(
    "oncall_agent_dependency_request_duration_seconds",
    "Dependency call latency in seconds.",
    ["dependency", "operation", "status"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
READINESS_STATUS = Gauge(
    "oncall_agent_readiness_status",
    "Readiness state for named checks. 1 means ready, 0 means not ready.",
    ["check"],
)
RECOMMENDATION_QUALITY_SCORE = Histogram(
    "oncall_agent_recommendation_quality_score",
    "Recommendation quality dimension scores emitted by the agent recommendation pipeline.",
    ["mode", "dimension"],
    buckets=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
)
RECOMMENDATION_REWRITE_TRIGGERS_TOTAL = Counter(
    "oncall_agent_recommendation_rewrite_triggers_total",
    "Recommendation rewrite passes triggered by anti-copy guardrails.",
    ["mode", "reason"],
)


def metrics_response() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def set_readiness_check(check_name: str, ready: bool) -> None:
    READINESS_STATUS.labels(check=check_name).set(1.0 if ready else 0.0)


def record_recommendation_quality(*, mode: str, quality: "RecommendationQuality") -> None:
    RECOMMENDATION_QUALITY_SCORE.labels(
        mode=mode,
        dimension="actionability",
    ).observe(quality.actionability_score)
    RECOMMENDATION_QUALITY_SCORE.labels(
        mode=mode,
        dimension="specificity",
    ).observe(quality.specificity_score)
    RECOMMENDATION_QUALITY_SCORE.labels(
        mode=mode,
        dimension="evidence_coverage",
    ).observe(quality.evidence_coverage_score)
    RECOMMENDATION_QUALITY_SCORE.labels(
        mode=mode,
        dimension="duplication",
    ).observe(quality.duplication_score)


def record_rewrite_trigger(*, mode: str, reason: str) -> None:
    RECOMMENDATION_REWRITE_TRIGGERS_TOTAL.labels(mode=mode, reason=reason).inc()


@contextmanager
def observe_dependency(dependency: str, operation: str) -> Iterator[None]:
    started_at = perf_counter()
    status = "success"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        duration = perf_counter() - started_at
        DEPENDENCY_REQUESTS_TOTAL.labels(
            dependency=dependency,
            operation=operation,
            status=status,
        ).inc()
        DEPENDENCY_REQUEST_DURATION_SECONDS.labels(
            dependency=dependency,
            operation=operation,
            status=status,
        ).observe(duration)

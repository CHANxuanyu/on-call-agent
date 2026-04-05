"""Small local demo target for the deployment-regression incident family."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread

from pydantic import BaseModel, ConfigDict, Field


class DemoServiceHealthResponse(BaseModel):
    """Health snapshot exposed by the demo service."""

    model_config = ConfigDict(extra="forbid")

    service: str = Field(min_length=1)
    current_version: str = Field(min_length=1)
    healthy: bool
    status: str = Field(min_length=1)
    degraded_reason: str | None = None
    error_rate: float
    checked_at: datetime


class DemoServiceDeploymentResponse(BaseModel):
    """Deployment snapshot exposed by the demo service."""

    model_config = ConfigDict(extra="forbid")

    service: str = Field(min_length=1)
    current_version: str = Field(min_length=1)
    previous_version: str = Field(min_length=1)
    bad_version: str = Field(min_length=1)
    deployed_at: datetime
    recent_deployment: bool
    bad_release_active: bool
    rollback_available: bool


class DemoServiceMetricsResponse(BaseModel):
    """Small runtime metrics snapshot exposed by the demo service."""

    model_config = ConfigDict(extra="forbid")

    service: str = Field(min_length=1)
    current_version: str = Field(min_length=1)
    error_rate: float
    timeout_rate: float
    latency_p95_ms: int
    window_seconds: int


class DemoServiceRollbackResponse(BaseModel):
    """Rollback response emitted by the demo service."""

    model_config = ConfigDict(extra="forbid")

    service: str = Field(min_length=1)
    rollback_applied: bool
    rolled_back_from: str = Field(min_length=1)
    rolled_back_to: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    completed_at: datetime


@dataclass(slots=True)
class _DemoServiceState:
    service: str
    bad_version: str
    previous_version: str
    deployed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    degraded_reason: str = "Requests started timing out after the recent deployment."
    lock: Lock = field(default_factory=Lock)

    @property
    def current_version(self) -> str:
        return self.bad_version

    def health_payload(self) -> DemoServiceHealthResponse:
        with self.lock:
            bad_release_active = self.bad_release_active
            current_version = self.current_runtime_version
        return DemoServiceHealthResponse(
            service=self.service,
            current_version=current_version,
            healthy=not bad_release_active,
            status="healthy" if not bad_release_active else "degraded",
            degraded_reason=self.degraded_reason if bad_release_active else None,
            error_rate=0.01 if not bad_release_active else 0.41,
            checked_at=datetime.now(UTC),
        )

    def deployment_payload(self) -> DemoServiceDeploymentResponse:
        with self.lock:
            current_version = self.current_runtime_version
            bad_release_active = self.bad_release_active
            deployed_at = self.deployed_at
        return DemoServiceDeploymentResponse(
            service=self.service,
            current_version=current_version,
            previous_version=self.previous_version,
            bad_version=self.bad_version,
            deployed_at=deployed_at,
            recent_deployment=True,
            bad_release_active=bad_release_active,
            rollback_available=bad_release_active,
        )

    def metrics_payload(self) -> DemoServiceMetricsResponse:
        with self.lock:
            current_version = self.current_runtime_version
            bad_release_active = self.bad_release_active
        return DemoServiceMetricsResponse(
            service=self.service,
            current_version=current_version,
            error_rate=0.01 if not bad_release_active else 0.41,
            timeout_rate=0.0 if not bad_release_active else 0.24,
            latency_p95_ms=140 if not bad_release_active else 1800,
            window_seconds=300,
        )

    def rollback(self) -> DemoServiceRollbackResponse:
        with self.lock:
            if not self.bad_release_active:
                msg = "rollback is unavailable because the known bad release is no longer active"
                raise ValueError(msg)
            rolled_back_from = self.current_runtime_version
            self.current_runtime_version = self.previous_version
            self.deployed_at = datetime.now(UTC)
        return DemoServiceRollbackResponse(
            service=self.service,
            rollback_applied=True,
            rolled_back_from=rolled_back_from,
            rolled_back_to=self.previous_version,
            summary=(
                f"Rolled {self.service} back from {rolled_back_from} to {self.previous_version}."
            ),
            completed_at=datetime.now(UTC),
        )

    current_runtime_version: str = field(init=False)

    def __post_init__(self) -> None:
        self.current_runtime_version = self.bad_version

    @property
    def bad_release_active(self) -> bool:
        return self.current_runtime_version == self.bad_version


def _write_json_response(
    handler: BaseHTTPRequestHandler,
    *,
    status: HTTPStatus,
    payload: BaseModel | dict[str, object],
) -> None:
    body = (
        payload.model_dump(mode="json")
        if isinstance(payload, BaseModel)
        else payload
    )
    encoded = json.dumps(body, sort_keys=True).encode("utf-8")
    handler.send_response(status.value)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)


def _demo_handler(state: _DemoServiceState) -> type[BaseHTTPRequestHandler]:
    class DemoRequestHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                health = state.health_payload()
                status = HTTPStatus.OK if health.healthy else HTTPStatus.SERVICE_UNAVAILABLE
                _write_json_response(self, status=status, payload=health)
                return
            if self.path == "/deployment":
                _write_json_response(
                    self,
                    status=HTTPStatus.OK,
                    payload=state.deployment_payload(),
                )
                return
            if self.path == "/metrics":
                _write_json_response(
                    self,
                    status=HTTPStatus.OK,
                    payload=state.metrics_payload(),
                )
                return
            _write_json_response(
                self,
                status=HTTPStatus.NOT_FOUND,
                payload={"message": f"unknown path: {self.path}"},
            )

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/rollback":
                _write_json_response(
                    self,
                    status=HTTPStatus.NOT_FOUND,
                    payload={"message": f"unknown path: {self.path}"},
                )
                return
            try:
                response = state.rollback()
            except ValueError as exc:
                _write_json_response(
                    self,
                    status=HTTPStatus.CONFLICT,
                    payload={"message": str(exc)},
                )
                return
            _write_json_response(self, status=HTTPStatus.OK, payload=response)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

    return DemoRequestHandler


@dataclass(slots=True)
class DemoDeploymentTargetServer:
    """Small in-process HTTP server used by the live deployment-regression demo path."""

    host: str = "127.0.0.1"
    port: int = 0
    service: str = "payments-api"
    bad_version: str = "2.1.0"
    previous_version: str = "2.0.9"
    _state: _DemoServiceState = field(init=False)
    _server: ThreadingHTTPServer = field(init=False)
    _thread: Thread | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self._state = _DemoServiceState(
            service=self.service,
            bad_version=self.bad_version,
            previous_version=self.previous_version,
        )
        self._server = ThreadingHTTPServer(
            (self.host, self.port),
            _demo_handler(self._state),
        )

    @property
    def bound_port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.bound_port}"

    def serve_forever(self) -> None:
        self._server.serve_forever(poll_interval=0.1)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = Thread(target=self.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def __enter__(self) -> DemoDeploymentTargetServer:
        self.start()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

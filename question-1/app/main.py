from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.v1 import router as v1_router
from app.api.v2 import router as v2_router
from app.api.v3 import router as v3_router
from app.data_store.in_memory_store import InMemoryDocumentStore
from app.indexing.lexical_index import BM25LexicalIndex
from app.indexing.tokenizer import Tokenizer
from app.observability.logging import configure_logging
from app.observability.metrics import metrics_response, set_readiness_check
from app.observability.middleware import ObservabilityMiddleware
from app.security import SlidingWindowRateLimiter, load_security_settings, log_security_startup
from app.services.agent_service import AgentService
from app.services.document_service import DocumentService
from app.services.semantic_search_service import SemanticSearchService


PROJECT_ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger(__name__)


configure_logging()


def create_app(
    *,
    data_dir: Path | None = None,
    semantic_search_service: SemanticSearchService | None = None,
    agent_service: AgentService | None = None,
) -> FastAPI:
    templates = Jinja2Templates(directory=str(PROJECT_ROOT / "templates"))
    security_settings = load_security_settings()
    document_service = DocumentService(
        store=InMemoryDocumentStore(),
        index=BM25LexicalIndex(tokenizer=Tokenizer()),
    )
    semantic_service = semantic_search_service or SemanticSearchService()
    semantic_service.set_lexical_service(document_service)
    resolved_data_dir = data_dir or PROJECT_ROOT / "data"
    phase3_agent_service = agent_service or AgentService(data_dir=resolved_data_dir)
    v3_chat_rate_limiter = SlidingWindowRateLimiter(limit=security_settings.rate_limit_per_min)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log_security_startup(security_settings)
        logger.info(
            "application_starting",
            extra={
                "event": "application_starting",
                "data_dir": str(resolved_data_dir),
                "log_level": os.getenv("LOG_LEVEL", "INFO").upper(),
            },
        )
        _set_readiness(app, "startup", False, detail="startup in progress")
        _set_readiness(app, "catalog", False, detail="catalog not generated yet")
        _set_readiness(app, "document_index", False, detail="documents not loaded yet")
        _set_readiness(app, "semantic_index", False, detail="semantic index not warmed yet")

        try:
            document_count = document_service.load_documents_from_directory(resolved_data_dir)
            semantic_count = semantic_service.load_documents_from_directory(resolved_data_dir)
            semantic_service.warmup()
            catalog_path = phase3_agent_service.ensure_catalog()
            app.state.document_service = document_service
            app.state.semantic_search_service = semantic_service
            app.state.agent_service = phase3_agent_service
            app.state.templates = templates

            _set_readiness(
                app,
                "document_index",
                document_count > 0,
                detail=f"{document_count} HTML document(s) loaded",
            )
            _set_readiness(
                app,
                "semantic_index",
                semantic_count > 0,
                detail=f"{semantic_count} HTML document(s) indexed for semantic search",
            )
            _set_readiness(
                app,
                "catalog",
                catalog_path.exists(),
                detail=f"catalog path: {catalog_path}",
            )
            _set_readiness(app, "startup", True, detail="startup complete")

            logger.info(
                "application_started",
                extra={
                    "event": "application_started",
                    "document_count": document_count,
                    "semantic_document_count": semantic_count,
                    "catalog_path": str(catalog_path),
                },
            )
            yield
        except Exception:
            logger.exception(
                "application_startup_failed",
                extra={
                    "event": "application_startup_failed",
                    "data_dir": str(resolved_data_dir),
                },
            )
            _set_readiness(app, "startup", False, detail="startup failed")
            raise
        finally:
            _shutdown_semantic_service(semantic_service)
            _set_readiness(app, "startup", False, detail="application shutting down")
            logger.info("application_stopped", extra={"event": "application_stopped"})

    app = FastAPI(
        title="On-Call Assistant",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.readiness_checks = {}
    app.state.data_dir = resolved_data_dir
    app.state.security_settings = security_settings
    app.state.v3_chat_rate_limiter = v3_chat_rate_limiter
    app.add_middleware(ObservabilityMiddleware)
    app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "static")), name="static")
    app.include_router(v1_router)
    app.include_router(v2_router)
    app.include_router(v3_router)

    @app.get("/healthz", include_in_schema=False)
    def healthz(request: Request) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "ok",
                "service": request.app.title,
                "version": request.app.version,
            },
        )

    @app.get("/readyz", include_in_schema=False)
    def readyz(request: Request) -> JSONResponse:
        readiness_checks: dict[str, dict[str, str | bool]] = getattr(request.app.state, "readiness_checks", {})
        ready = bool(readiness_checks) and all(bool(check["ready"]) for check in readiness_checks.values())
        return JSONResponse(
            status_code=status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "ready": ready,
                "checks": readiness_checks,
            },
        )

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return metrics_response()

    return app


app = create_app()


def _set_readiness(app: FastAPI, check_name: str, ready: bool, *, detail: str) -> None:
    app.state.readiness_checks[check_name] = {"ready": ready, "detail": detail}
    set_readiness_check(check_name, ready)


def _shutdown_semantic_service(semantic_service: object) -> None:
    shutdown = getattr(semantic_service, "shutdown", None)
    if not callable(shutdown):
        return
    shutdown()

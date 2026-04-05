from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import HTMLResponse

from app.core.schemas import (
    DocumentCreateRequest,
    DocumentCreateResponse,
    SearchResponse,
    SearchResult,
)
from app.security import require_api_key
from app.services.document_service import DocumentService
from app.services.semantic_search_service import SemanticSearchService


router = APIRouter(prefix="/v1", tags=["phase-1"])


@router.post("/documents", response_model=DocumentCreateResponse, status_code=status.HTTP_201_CREATED)
def create_document(
    payload: DocumentCreateRequest,
    request: Request,
    _: None = Depends(require_api_key),
) -> DocumentCreateResponse:
    service = _get_document_service(request)
    document = service.ingest_document(document_id=payload.id, html=payload.html)
    semantic_service = _get_semantic_search_service(request)
    if semantic_service is not None:
        semantic_service.ingest_document(document_id=payload.id, html=payload.html)
    return DocumentCreateResponse(id=document.id, title=document.title)


@router.get("/search", response_model=SearchResponse)
def search_documents(
    request: Request,
    q: str = Query(default="", description="Keyword query"),
) -> SearchResponse:
    service = _get_document_service(request)
    hits = service.search(q)
    return SearchResponse(
        query=q,
        results=[
            SearchResult(
                id=hit.id,
                title=hit.title,
                snippet=hit.snippet,
                score=hit.score,
            )
            for hit in hits
        ],
    )


@router.get("", response_class=HTMLResponse, include_in_schema=False)
def search_page(
    request: Request,
    q: str = Query(default="", description="Optional initial page query"),
) -> HTMLResponse:
    service = _get_document_service(request)
    hits = service.search(q) if q.strip() else []
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="v1.html",
        context={
            "query": q,
            "results": hits,
        },
    )


def _get_document_service(request: Request) -> DocumentService:
    return request.app.state.document_service


def _get_semantic_search_service(request: Request) -> SemanticSearchService | None:
    return getattr(request.app.state, "semantic_search_service", None)

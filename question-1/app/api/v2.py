from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from app.core.schemas import SearchResponse, SearchResult
from app.services.semantic_search_service import SemanticSearchService


router = APIRouter(prefix="/v2", tags=["phase-2"])


@router.get("/search", response_model=SearchResponse)
def search_documents(
    request: Request,
    q: str = Query(default="", description="Semantic search query"),
) -> SearchResponse:
    service = _get_semantic_search_service(request)
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
    q: str = Query(default="", description="Optional initial semantic query"),
) -> HTMLResponse:
    service = _get_semantic_search_service(request)
    hits = service.search(q) if q.strip() else []
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="v2.html",
        context={
            "query": q,
            "results": hits,
        },
    )


def _get_semantic_search_service(request: Request) -> SemanticSearchService:
    return request.app.state.semantic_search_service

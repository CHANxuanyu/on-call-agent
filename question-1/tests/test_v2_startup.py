from pathlib import Path
import unicodedata

import numpy as np
from fastapi.testclient import TestClient

from app.indexing.semantic_index import InMemorySemanticIndex
from app.main import create_app
from app.services.semantic_search_service import SemanticSearchService


DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class CountingSemanticEmbedder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def encode(self, texts: list[str] | tuple[str, ...]) -> np.ndarray:
        self.calls.append(list(texts))
        rows = []
        for text in texts:
            normalized = unicodedata.normalize("NFKC", text)
            rows.append(
                [
                    float(len(normalized)),
                    float(sum(ord(char) for char in normalized) % 251),
                    float(normalized.count("故障") + normalized.count("模型") + 1),
                ]
            )
        return np.asarray(rows, dtype=np.float32)


class ShutdownAwareChunker:
    def __init__(self) -> None:
        self.shutdown_called = False

    def chunk_document(self, document_id: str, html: str, *, title: str | None = None):
        del document_id, html, title
        return []

    def shutdown(self) -> None:
        self.shutdown_called = True


class ShutdownAwareIndex(InMemorySemanticIndex):
    def __init__(self) -> None:
        super().__init__(embedder=CountingSemanticEmbedder())
        self.shutdown_called = False

    def shutdown(self) -> None:
        self.shutdown_called = True
        super().shutdown()


class StubSemanticService:
    def __init__(self) -> None:
        self.shutdown_called = False

    def set_lexical_service(self, lexical_service) -> None:
        del lexical_service

    def load_documents_from_directory(self, directory) -> int:
        del directory
        return 0

    def warmup(self) -> None:
        return None

    def search(self, query: str, *, limit: int = 10) -> list[object]:
        del query, limit
        return []

    def shutdown(self) -> None:
        self.shutdown_called = True


def test_app_startup_warms_semantic_index_before_first_query() -> None:
    embedder = CountingSemanticEmbedder()
    semantic_service = SemanticSearchService(index=InMemorySemanticIndex(embedder=embedder))
    app = create_app(data_dir=DATA_DIR, semantic_search_service=semantic_service)

    with TestClient(app) as client:
        assert len(embedder.calls) == 1
        assert len(embedder.calls[0]) > 1

        response = client.get("/v2/search", params={"q": "黑客攻击"})

        assert response.status_code == 200
        assert len(embedder.calls) == 2
        assert embedder.calls[1] == ["黑客攻击"]


def test_semantic_search_service_shutdown_closes_index_and_chunker() -> None:
    chunker = ShutdownAwareChunker()
    index = ShutdownAwareIndex()
    semantic_service = SemanticSearchService(chunker=chunker, index=index)

    semantic_service.shutdown()
    semantic_service.shutdown()

    assert index.shutdown_called is True
    assert chunker.shutdown_called is True


def test_app_shutdown_calls_semantic_service_shutdown() -> None:
    semantic_service = StubSemanticService()
    app = create_app(data_dir=DATA_DIR, semantic_search_service=semantic_service)

    with TestClient(app):
        assert semantic_service.shutdown_called is False

    assert semantic_service.shutdown_called is True

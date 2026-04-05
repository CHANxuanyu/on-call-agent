from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Protocol, Sequence

import numpy as np

from app.indexing.chunker import SemanticChunk


DEFAULT_MODEL_NAMES = (
    "paraphrase-multilingual-mpnet-base-v2",
    "paraphrase-multilingual-MiniLM-L12-v2",
)


class EmbeddingModel(Protocol):
    def encode(self, texts: Sequence[str]) -> np.ndarray: ...


@dataclass(slots=True)
class ChunkSearchHit:
    chunk: SemanticChunk
    score: float


class SentenceTransformerEmbedder:
    def __init__(self, model_names: Sequence[str] = DEFAULT_MODEL_NAMES) -> None:
        self._model_names = tuple(model_names)
        self._model = None
        self.model_name: str | None = None

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)

        model = self._load_model()
        embeddings = model.encode(
            list(texts),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return _normalize_embeddings(np.asarray(embeddings, dtype=np.float32))

    def _load_model(self):
        if self._model is not None:
            return self._model

        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:  # pragma: no cover - exercised in runtime environments
            raise RuntimeError(
                "Phase 2 semantic search requires the sentence-transformers package."
            ) from exc

        errors: list[str] = []
        for model_name in self._model_names:
            try:
                self._model = SentenceTransformer(model_name)
                self.model_name = model_name
                return self._model
            except Exception as exc:  # pragma: no cover - depends on local model availability
                errors.append(f"{model_name}: {exc}")

        joined_errors = "; ".join(errors)
        raise RuntimeError(f"Unable to load a semantic embedding model. {joined_errors}")

    def shutdown(self) -> None:
        self._model = None


class InMemorySemanticIndex:
    def __init__(self, embedder: EmbeddingModel | None = None) -> None:
        self._embedder = embedder or SentenceTransformerEmbedder()
        self._chunks: dict[str, SemanticChunk] = {}
        self._embeddings: dict[str, np.ndarray] = {}
        self._doc_to_chunk_ids: dict[str, set[str]] = defaultdict(set)
        self._chunk_order: list[str] = []
        self._embedding_matrix = np.zeros((0, 0), dtype=np.float32)

    def index_chunks(self, chunks: Sequence[SemanticChunk]) -> None:
        if not chunks:
            return

        embeddings = _normalize_embeddings(self._embedder.encode([chunk.search_text for chunk in chunks]))
        if embeddings.ndim == 1:
            embeddings = embeddings.reshape(1, -1)

        for chunk, embedding in zip(chunks, embeddings):
            self._chunks[chunk.chunk_id] = chunk
            self._embeddings[chunk.chunk_id] = embedding.astype(np.float32, copy=False)
            self._doc_to_chunk_ids[chunk.doc_id].add(chunk.chunk_id)

        self._rebuild_matrix()

    def remove_document(self, doc_id: str) -> None:
        chunk_ids = self._doc_to_chunk_ids.pop(doc_id, set())
        if not chunk_ids:
            return

        for chunk_id in chunk_ids:
            self._chunks.pop(chunk_id, None)
            self._embeddings.pop(chunk_id, None)

        self._rebuild_matrix()

    def search(self, query: str, *, limit: int = 20) -> list[ChunkSearchHit]:
        if not query.strip() or not self._chunks:
            return []

        query_embedding = _normalize_embeddings(self._embedder.encode([query]))
        if query_embedding.size == 0:
            return []

        if query_embedding.ndim == 1:
            query_embedding = query_embedding.reshape(1, -1)

        scores = self._embedding_matrix @ query_embedding[0]
        ranked_indices = np.argsort(scores)[::-1]

        hits: list[ChunkSearchHit] = []
        for index in ranked_indices[:limit]:
            score = float(scores[index])
            if not np.isfinite(score):
                continue
            chunk_id = self._chunk_order[index]
            hits.append(ChunkSearchHit(chunk=self._chunks[chunk_id], score=score))

        return hits

    def get_representative_chunk(self, doc_id: str) -> SemanticChunk | None:
        chunk_ids = sorted(self._doc_to_chunk_ids.get(doc_id, ()))
        if not chunk_ids:
            return None
        return self._chunks.get(chunk_ids[0])

    def shutdown(self) -> None:
        _shutdown_embedder(self._embedder)
        self._chunks.clear()
        self._embeddings.clear()
        self._doc_to_chunk_ids.clear()
        self._chunk_order.clear()
        self._embedding_matrix = np.zeros((0, 0), dtype=np.float32)

    def _rebuild_matrix(self) -> None:
        self._chunk_order = sorted(self._chunks)
        if not self._chunk_order:
            self._embedding_matrix = np.zeros((0, 0), dtype=np.float32)
            return

        self._embedding_matrix = np.vstack(
            [self._embeddings[chunk_id] for chunk_id in self._chunk_order]
        ).astype(np.float32, copy=False)


def _normalize_embeddings(embeddings: np.ndarray) -> np.ndarray:
    if embeddings.size == 0:
        return embeddings.astype(np.float32, copy=False)

    matrix = np.asarray(embeddings, dtype=np.float32)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)

    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def _shutdown_embedder(embedder: object) -> None:
    shutdown = getattr(embedder, "shutdown", None)
    if not callable(shutdown):
        return

    cast_shutdown = _as_shutdown(shutdown)
    cast_shutdown()


def _as_shutdown(shutdown: Callable[..., Any]) -> Callable[[], Any]:
    return shutdown

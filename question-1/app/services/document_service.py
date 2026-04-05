from __future__ import annotations

from pathlib import Path

from app.core.html_parser import parse_html_document
from app.data_store.base import BaseDocumentStore
from app.data_store.in_memory_store import StoredDocument
from app.indexing.lexical_index import BM25LexicalIndex, SearchHit


class DocumentService:
    def __init__(self, store: BaseDocumentStore, index: BM25LexicalIndex) -> None:
        self._store = store
        self._index = index

    def ingest_document(self, document_id: str, html: str) -> StoredDocument:
        normalized_id = document_id.strip()
        parsed_document = parse_html_document(normalized_id, html)
        stored_document = StoredDocument(
            id=normalized_id,
            html=html,
            title=parsed_document.title,
            visible_text=parsed_document.visible_text,
        )
        self._store.upsert(stored_document)
        self._index.index_document(
            document_id=stored_document.id,
            title=stored_document.title,
            text=stored_document.visible_text,
        )
        return stored_document

    def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        return self._index.search(query.strip(), limit=limit)

    def load_documents_from_directory(self, directory: Path) -> int:
        if not directory.exists():
            return 0

        indexed_count = 0
        for path in sorted(directory.glob("*.html")):
            html = path.read_text(encoding="utf-8")
            self.ingest_document(document_id=path.stem, html=html)
            indexed_count += 1

        return indexed_count

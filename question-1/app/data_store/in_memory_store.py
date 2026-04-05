from __future__ import annotations

from dataclasses import dataclass

from .base import BaseDocumentStore


@dataclass(slots=True)
class StoredDocument:
    id: str
    html: str
    title: str
    visible_text: str

class InMemoryDocumentStore(BaseDocumentStore):
    def __init__(self) -> None:
        self._documents: dict[str, StoredDocument] = {}

    def upsert(self, document: StoredDocument) -> StoredDocument:
        self._documents[document.id] = document
        return document

    def get(self, document_id: str) -> StoredDocument | None:
        return self._documents.get(document_id)

    def list_all(self) -> list[StoredDocument]:
        return list(self._documents.values())

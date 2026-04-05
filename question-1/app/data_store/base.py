from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .in_memory_store import StoredDocument


class BaseDocumentStore(ABC):
    @abstractmethod
    def upsert(self, document: StoredDocument) -> StoredDocument:
        raise NotImplementedError

    @abstractmethod
    def get(self, document_id: str) -> StoredDocument | None:
        raise NotImplementedError

    @abstractmethod
    def list_all(self) -> list[StoredDocument]:
        raise NotImplementedError

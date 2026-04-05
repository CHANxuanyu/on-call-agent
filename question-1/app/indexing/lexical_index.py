from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import math
import re

from app.indexing.tokenizer import Token, Tokenizer


SNIPPET_MAX_CHARS = 180
SNIPPET_PREFIX_WINDOW = 55
SNIPPET_SUFFIX_WINDOW = 110
BOUNDARY_CHARS = " \t\r\n。！？；;,.!?:："
POSITION_BONUS_WEIGHT = 0.05


@dataclass(slots=True)
class IndexedDocument:
    id: str
    title: str
    text: str
    tokens: list[Token]
    term_frequencies: Counter[str]
    positions: dict[str, list[Token]]

    @property
    def length(self) -> int:
        return len(self.tokens)


@dataclass(slots=True)
class SearchHit:
    id: str
    title: str
    snippet: str
    score: float


class BM25LexicalIndex:
    def __init__(self, tokenizer: Tokenizer, *, k1: float = 1.5, b: float = 0.75) -> None:
        self._tokenizer = tokenizer
        self._k1 = k1
        self._b = b
        self._documents: dict[str, IndexedDocument] = {}
        self._postings: dict[str, dict[str, int]] = defaultdict(dict)
        self._total_document_length = 0

    def index_document(self, document_id: str, title: str, text: str) -> None:
        if document_id in self._documents:
            self.remove_document(document_id)

        tokens = self._tokenizer.tokenize(text)
        term_frequencies = Counter(token.term for token in tokens)
        positions: dict[str, list[Token]] = defaultdict(list)
        for token in tokens:
            positions[token.term].append(token)

        indexed_document = IndexedDocument(
            id=document_id,
            title=title,
            text=text,
            tokens=tokens,
            term_frequencies=term_frequencies,
            positions=dict(positions),
        )

        self._documents[document_id] = indexed_document
        self._total_document_length += indexed_document.length

        for term, frequency in term_frequencies.items():
            self._postings[term][document_id] = frequency

    def remove_document(self, document_id: str) -> None:
        document = self._documents.pop(document_id, None)
        if document is None:
            return

        self._total_document_length -= document.length

        for term in document.term_frequencies:
            postings = self._postings.get(term)
            if postings is None:
                continue
            postings.pop(document_id, None)
            if not postings:
                self._postings.pop(term, None)

    def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        query_tokens = self._tokenizer.tokenize(query)
        if not query_tokens:
            return []

        query_terms = Counter(token.term for token in query_tokens)
        candidate_ids = self._candidate_document_ids(query_terms)
        if not candidate_ids:
            return []

        average_document_length = self._average_document_length()
        hits: list[SearchHit] = []

        for document_id in candidate_ids:
            document = self._documents[document_id]
            focus = self._first_match_position(document, query_terms)
            score = self._score(document, query_terms, average_document_length) + self._position_bonus(
                document, focus
            )
            if score <= 0:
                continue

            snippet = self._build_snippet(document, focus)
            hits.append(
                SearchHit(
                    id=document.id,
                    title=document.title,
                    snippet=snippet,
                    score=round(score, 4),
                )
            )

        hits.sort(key=lambda hit: (-hit.score, hit.id))
        return hits[:limit]

    def _candidate_document_ids(self, query_terms: Counter[str]) -> set[str]:
        candidate_ids: set[str] = set()
        for term in query_terms:
            candidate_ids.update(self._postings.get(term, {}).keys())
        return candidate_ids

    def _average_document_length(self) -> float:
        if not self._documents:
            return 0.0
        return self._total_document_length / len(self._documents)

    def _score(
        self,
        document: IndexedDocument,
        query_terms: Counter[str],
        average_document_length: float,
    ) -> float:
        score = 0.0
        document_length = max(document.length, 1)
        average_document_length = max(average_document_length, 1.0)
        total_documents = len(self._documents)

        for term, query_frequency in query_terms.items():
            postings = self._postings.get(term)
            if not postings or document.id not in postings:
                continue

            document_frequency = len(postings)
            term_frequency = postings[document.id]
            idf = math.log(1 + (total_documents - document_frequency + 0.5) / (document_frequency + 0.5))
            denominator = term_frequency + self._k1 * (
                1 - self._b + self._b * document_length / average_document_length
            )
            score += query_frequency * idf * ((term_frequency * (self._k1 + 1)) / denominator)

        return score

    def _build_snippet(self, document: IndexedDocument, focus: Token | None) -> str:
        if focus is None:
            return _normalize_snippet(document.text[:SNIPPET_MAX_CHARS])

        start = max(0, focus.start - SNIPPET_PREFIX_WINDOW)
        end = min(len(document.text), max(focus.end + SNIPPET_SUFFIX_WINDOW, start + SNIPPET_MAX_CHARS))
        start = _seek_boundary(document.text, start, direction=-1)
        end = _seek_boundary(document.text, end, direction=1)
        snippet = _normalize_snippet(document.text[start:end])

        if start > 0:
            snippet = f"...{snippet}"
        if end < len(document.text):
            snippet = f"{snippet}..."

        return snippet

    def _first_match_position(
        self, document: IndexedDocument, query_terms: Counter[str]
    ) -> Token | None:
        candidates = [
            positions[0]
            for term, positions in document.positions.items()
            if term in query_terms and positions
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda token: (token.start, token.end))

    def _position_bonus(self, document: IndexedDocument, focus: Token | None) -> float:
        if focus is None or not document.text:
            return 0.0

        # Keep BM25 dominant and use position only as a light tie-breaker.
        normalized_offset = focus.start / max(len(document.text), 1)
        return POSITION_BONUS_WEIGHT * (1 - normalized_offset)


def _normalize_snippet(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _seek_boundary(text: str, position: int, *, direction: int) -> int:
    if not text:
        return 0

    position = max(0, min(position, len(text)))
    if direction not in (-1, 1):
        raise ValueError("direction must be -1 or 1")

    if direction < 0:
        while position > 0:
            if text[position - 1] in BOUNDARY_CHARS:
                break
            position -= 1
        return position

    while position < len(text):
        if text[position] in BOUNDARY_CHARS:
            break
        position += 1
    return position

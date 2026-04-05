from __future__ import annotations

from dataclasses import dataclass
from html import unescape
import re
import unicodedata

from bs4 import BeautifulSoup
from bs4.element import Tag

from app.core.html_parser import REMOVED_TAGS, parse_html_document


WHITESPACE_RE = re.compile(r"\s+")
SECTION_HEADINGS = {"h2": 2, "h3": 3}
CONTENT_TAGS = {"p", "li"}
NON_VISIBLE_CONTAINERS = {"head"}


@dataclass(slots=True)
class SemanticChunk:
    chunk_id: str
    doc_id: str
    title: str
    section_path: str
    text: str
    search_text: str


class HtmlSectionChunker:
    """Splits SOP HTML into section-oriented semantic chunks."""

    def chunk_document(self, document_id: str, html: str, *, title: str | None = None) -> list[SemanticChunk]:
        parsed_document = parse_html_document(document_id, html)
        resolved_title = title or parsed_document.title

        soup = BeautifulSoup(html, "html5lib")
        for tag_name in REMOVED_TAGS:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        root = soup.body or soup.find("html") or soup
        section_path: list[str] = []
        text_buffer: list[str] = []
        chunks: list[SemanticChunk] = []

        for element in root.find_all(list(SECTION_HEADINGS) + list(CONTENT_TAGS), recursive=True):
            if _has_non_visible_ancestor(element):
                continue

            text = _normalize_text(element.get_text(" ", strip=True))
            if not text:
                continue

            if element.name in SECTION_HEADINGS:
                _flush_chunk(
                    chunks=chunks,
                    doc_id=document_id,
                    title=resolved_title,
                    section_path=section_path,
                    text_buffer=text_buffer,
                )
                section_path = _update_section_path(section_path, SECTION_HEADINGS[element.name], text)
                continue

            text_buffer.append(text)

        _flush_chunk(
            chunks=chunks,
            doc_id=document_id,
            title=resolved_title,
            section_path=section_path,
            text_buffer=text_buffer,
        )

        if chunks or not parsed_document.visible_text:
            return chunks

        fallback_text = parsed_document.visible_text
        return [
            SemanticChunk(
                chunk_id=f"{document_id}::chunk-001",
                doc_id=document_id,
                title=resolved_title,
                section_path="",
                text=fallback_text,
                search_text=_build_search_text(resolved_title, "", fallback_text),
            )
        ]


def _flush_chunk(
    *,
    chunks: list[SemanticChunk],
    doc_id: str,
    title: str,
    section_path: list[str],
    text_buffer: list[str],
) -> None:
    text = _normalize_text(" ".join(text_buffer))
    if not text:
        text_buffer.clear()
        return

    section_path_text = " > ".join(section_path)
    chunk_number = len(chunks) + 1
    chunks.append(
        SemanticChunk(
            chunk_id=f"{doc_id}::chunk-{chunk_number:03d}",
            doc_id=doc_id,
            title=title,
            section_path=section_path_text,
            text=text,
            search_text=_build_search_text(title, section_path_text, text),
        )
    )
    text_buffer.clear()


def _build_search_text(title: str, section_path: str, text: str) -> str:
    return _normalize_text(" ".join(part for part in (title, section_path, text) if part))


def _update_section_path(current_path: list[str], level: int, heading: str) -> list[str]:
    if level <= 2:
        return [heading]

    if not current_path:
        return [heading]

    return [current_path[0], heading]


def _has_non_visible_ancestor(node: Tag) -> bool:
    current: Tag | None = node
    while current is not None and current.name != "[document]":
        if current.name in NON_VISIBLE_CONTAINERS or _is_hidden(current):
            return True
        current = current.parent if isinstance(current.parent, Tag) else None
    return False


def _is_hidden(tag: Tag) -> bool:
    if tag.has_attr("hidden"):
        return True

    aria_hidden = str(tag.attrs.get("aria-hidden", "")).strip().lower()
    if aria_hidden == "true":
        return True

    style = str(tag.attrs.get("style", "")).replace(" ", "").lower()
    return "display:none" in style or "visibility:hidden" in style


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", unescape(text).replace("\xa0", " "))
    return WHITESPACE_RE.sub(" ", normalized).strip()

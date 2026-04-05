from __future__ import annotations

from dataclasses import dataclass
from html import unescape
import re
import unicodedata
from typing import Iterator

from bs4 import BeautifulSoup
from bs4.element import Comment, NavigableString, Tag


WHITESPACE_RE = re.compile(r"\s+")
REMOVED_TAGS = ("script", "style", "noscript")
NON_VISIBLE_CONTAINERS = {"head"}


@dataclass(slots=True)
class ParsedDocument:
    id: str
    title: str
    visible_text: str


def parse_html_document(document_id: str, html: str) -> ParsedDocument:
    soup = BeautifulSoup(html, "html5lib")

    for tag_name in REMOVED_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    title = _extract_title(soup, document_id)
    root = _get_visible_root(soup)
    visible_chunks = list(_iter_visible_text(root))
    visible_text = _normalize_text(" ".join(visible_chunks))

    return ParsedDocument(id=document_id, title=title, visible_text=visible_text)


def _extract_title(soup: BeautifulSoup, fallback_id: str) -> str:
    title_tag = soup.find("title")
    if title_tag:
        title = _normalize_text(title_tag.get_text(" ", strip=True))
        if title:
            return title

    for h1 in soup.find_all("h1"):
        if _is_hidden(h1):
            continue
        title = _normalize_text(h1.get_text(" ", strip=True))
        if title:
            return title

    return fallback_id


def _get_visible_root(soup: BeautifulSoup) -> Tag:
    return soup.body or soup.find("html") or soup


def _iter_visible_text(root: Tag) -> Iterator[str]:
    for node in root.descendants:
        if not isinstance(node, NavigableString):
            continue
        if isinstance(node, Comment):
            continue

        parent = node.parent
        if parent is None or _has_non_visible_ancestor(parent):
            continue

        chunk = _normalize_text(str(node))
        if chunk:
            yield chunk


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


def _normalize_text(text: str, *, normalize_unicode: bool = True) -> str:
    decoded = unescape(text).replace("\xa0", " ")
    if normalize_unicode:
        decoded = unicodedata.normalize("NFKC", decoded)
    return WHITESPACE_RE.sub(" ", decoded).strip()

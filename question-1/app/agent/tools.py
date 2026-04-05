from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import logging
from pathlib import Path
import re
from typing import Any

from bs4 import BeautifulSoup

from app.core.html_parser import REMOVED_TAGS, parse_html_document
from app.observability.metrics import observe_dependency


CATALOG_FILE_NAME = "catalog.json"
PREVIEW_MAX_CHARS = 180
SUMMARY_MAX_CHARS = 220
MAX_THEMES = 5
MAX_SCENARIOS = 5
MAX_KEYWORDS = 40
KNOWN_OPERATIONAL_TERMS = (
    "oom",
    "内存溢出",
    "主从",
    "复制",
    "复制延迟",
    "从库",
    "慢查询",
    "连接池",
    "数据恢复",
    "服务",
    "超时",
    "降级",
    "故障",
    "集群",
    "节点",
    "k8s",
    "kubernetes",
    "ingress",
    "白屏",
    "cdn",
    "dns",
    "ddos",
    "入侵",
    "攻击",
    "漏洞",
    "安全事件",
    "etl",
    "spark",
    "推送",
    "崩溃",
    "模型",
    "推荐",
    "排序",
    "质量下降",
    "推理",
    "gpu",
)
KNOWN_ESCALATION_TERMS = (
    "p0",
    "p1",
    "p2",
    "响应流程",
    "故障响应",
    "升级流程",
    "故障分级",
    "升级",
    "war room",
    "事故",
    "上报",
    "通知",
)
TOKEN_RE = re.compile(r"[A-Za-z0-9/_-]+|[\u4e00-\u9fff]{2,6}")
logger = logging.getLogger(__name__)


class ToolExecutionError(ValueError):
    """Raised when a tool invocation is invalid or unsafe."""


@dataclass(slots=True)
class ToolResult:
    fname: str
    content: str

    @property
    def preview(self) -> str:
        if len(self.content) <= PREVIEW_MAX_CHARS:
            return self.content
        return f"{self.content[:PREVIEW_MAX_CHARS].rstrip()}..."


@dataclass(slots=True)
class ToolCallRecord:
    tool_name: str
    arguments: dict[str, str]
    status: str
    output_preview: str = ""

    def as_dict(self) -> dict[str, str | dict[str, str]]:
        return asdict(self)


@dataclass(slots=True)
class CatalogEntry:
    file_name: str
    doc_id: str
    title: str
    team_or_domain: str
    incident_themes: list[str]
    summary: str
    keywords: list[str]
    scenario_headings: list[str]
    scenario_snippets: list[str]
    operational_terms: list[str]
    escalation_terms: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ReadFileTool:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir.resolve()

    def read_file(self, fname: str) -> ToolResult:
        target = self._resolve_path(fname)
        with observe_dependency("filesystem", "read_file"):
            raw_text = target.read_text(encoding="utf-8")

        if target.suffix.lower() == ".html":
            parsed = parse_html_document(target.stem, raw_text)
            content = f"Title: {parsed.title}\nFile: {target.name}\n\n{parsed.visible_text}".strip()
        else:
            content = raw_text.strip()

        logger.info(
            "file_read_completed",
            extra={
                "event": "file_read_completed",
                "fname": target.name,
                "suffix": target.suffix.lower(),
            },
        )
        return ToolResult(fname=target.name, content=content)

    def _resolve_path(self, fname: str) -> Path:
        relative_path = Path(fname)
        if relative_path.is_absolute():
            raise ToolExecutionError("readFile only accepts paths relative to the data directory")

        target = (self._data_dir / relative_path).resolve()
        if self._data_dir != target and self._data_dir not in target.parents:
            raise ToolExecutionError("path traversal is not allowed")
        if not target.exists() or not target.is_file():
            raise ToolExecutionError(f"file not found: {fname}")
        return target


def build_catalog(data_dir: Path) -> list[CatalogEntry]:
    entries: list[CatalogEntry] = []
    for path in sorted(data_dir.glob("*.html")):
        html = path.read_text(encoding="utf-8")
        parsed = parse_html_document(path.stem, html)
        soup = BeautifulSoup(html, "html5lib")
        for tag_name in REMOVED_TAGS:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        entries.append(
            CatalogEntry(
                file_name=path.name,
                doc_id=path.stem,
                title=parsed.title,
                team_or_domain=_extract_team_or_domain(parsed.title),
                incident_themes=_extract_incident_themes(soup),
                summary=_extract_summary(soup, parsed.visible_text),
                keywords=_extract_keywords(soup, parsed.title, parsed.visible_text),
                scenario_headings=_extract_scenario_headings(soup),
                scenario_snippets=_extract_scenario_snippets(soup),
                operational_terms=_extract_known_terms(parsed.visible_text, KNOWN_OPERATIONAL_TERMS),
                escalation_terms=_extract_known_terms(parsed.visible_text, KNOWN_ESCALATION_TERMS),
            )
        )
    return entries


def write_catalog(data_dir: Path) -> Path:
    entries = build_catalog(data_dir)
    payload = {"files": [entry.as_dict() for entry in entries]}
    catalog_path = data_dir / CATALOG_FILE_NAME
    catalog_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return catalog_path


def load_catalog_from_text(text: str) -> list[CatalogEntry]:
    payload = json.loads(text) if text else {"files": []}
    entries: list[CatalogEntry] = []
    for item in payload.get("files", []):
        entries.append(
            CatalogEntry(
                file_name=item["file_name"],
                doc_id=item["doc_id"],
                title=item["title"],
                team_or_domain=item["team_or_domain"],
                incident_themes=item.get("incident_themes", []),
                summary=item.get("summary", ""),
                keywords=item.get("keywords", []),
                scenario_headings=item.get("scenario_headings", item.get("incident_themes", [])),
                scenario_snippets=item.get("scenario_snippets", []),
                operational_terms=item.get("operational_terms", []),
                escalation_terms=item.get("escalation_terms", []),
            )
        )
    return entries


def _extract_team_or_domain(title: str) -> str:
    normalized_title = title.replace("On-Call SOP", "").strip(" -")
    return normalized_title or title


def _extract_incident_themes(soup: BeautifulSoup) -> list[str]:
    themes: list[str] = []
    for heading in soup.find_all("h3"):
        text = heading.get_text(" ", strip=True)
        if not text:
            continue
        themes.append(text)
        if len(themes) >= MAX_THEMES:
            break
    return themes


def _extract_scenario_headings(soup: BeautifulSoup) -> list[str]:
    return _extract_incident_themes(soup)


def _extract_scenario_snippets(soup: BeautifulSoup) -> list[str]:
    snippets: list[str] = []
    for heading in soup.find_all("h3"):
        heading_text = " ".join(heading.get_text(" ", strip=True).split())
        if not heading_text:
            continue

        detail_parts: list[str] = []
        for sibling in heading.next_siblings:
            sibling_name = getattr(sibling, "name", None)
            if sibling_name in {"h2", "h3"}:
                break
            if sibling_name not in {"p", "li"}:
                continue

            sibling_text = " ".join(sibling.get_text(" ", strip=True).split())
            if sibling_text:
                detail_parts.append(sibling_text)
            if len(detail_parts) >= 2:
                break

        snippet_text = heading_text
        if detail_parts:
            snippet_text = f"{heading_text}：{' '.join(detail_parts)}"
        snippets.append(_truncate(snippet_text, limit=SUMMARY_MAX_CHARS))
        if len(snippets) >= MAX_SCENARIOS:
            break

    return snippets


def _extract_keywords(soup: BeautifulSoup, title: str, visible_text: str) -> list[str]:
    text_parts = [title]
    text_parts.extend(_extract_incident_themes(soup))
    text_parts.extend(_extract_scenario_snippets(soup))
    text_parts.append(_extract_summary(soup, visible_text))
    combined_text = " ".join(part for part in text_parts if part)
    return _tokenize_catalog_text(combined_text)


def _extract_known_terms(text: str, known_terms: tuple[str, ...]) -> list[str]:
    normalized_text = text.casefold()
    return [term for term in known_terms if term.casefold() in normalized_text]


def _extract_summary(soup: BeautifulSoup, visible_text: str) -> str:
    for paragraph in soup.find_all("p"):
        text = paragraph.get_text(" ", strip=True)
        text = " ".join(text.split())
        if not text:
            continue
        if text.startswith("文档编号：") or text.startswith("适用范围："):
            continue
        return _truncate(text, limit=SUMMARY_MAX_CHARS)

    return _truncate(visible_text, limit=SUMMARY_MAX_CHARS)


def _tokenize_catalog_text(text: str) -> list[str]:
    tokens: list[str] = []
    seen_tokens: set[str] = set()

    for match in TOKEN_RE.findall(text):
        token = match.casefold()
        if len(token) < 2 or token in seen_tokens:
            continue
        seen_tokens.add(token)
        tokens.append(token)
        if len(tokens) >= MAX_KEYWORDS:
            break

    return tokens


def _truncate(text: str, *, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."

from __future__ import annotations

import re
import unicodedata


WHITESPACE_RE = re.compile(r"\s+")
BROAD_ENTITY_MARKERS = ("服务器", "服务", "系统")
BROAD_OUTAGE_MARKERS = ("挂了", "不可用", "故障", "宕机")
SPECIFIC_DOMAIN_MARKERS = (
    "后端",
    "sre",
    "集群",
    "节点",
    "网关",
    "负载均衡",
    "实例",
    "数据库",
    "kubernetes",
    "cdn",
    "安全",
    "模型",
)
OUTAGE_EXPANSIONS = (
    "后端服务挂了",
    "SRE 集群故障",
    "服务不可用",
)


def expand_semantic_query(query: str) -> list[str]:
    normalized_query = _normalize_query(query)
    if not normalized_query:
        return []

    expanded_queries = [query.strip()]
    if _is_broad_outage_query(normalized_query):
        expanded_queries.extend(OUTAGE_EXPANSIONS)

    return _deduplicate_queries(expanded_queries)


def _is_broad_outage_query(normalized_query: str) -> bool:
    if any(marker in normalized_query for marker in SPECIFIC_DOMAIN_MARKERS):
        return False

    has_entity_marker = any(marker in normalized_query for marker in BROAD_ENTITY_MARKERS)
    has_outage_marker = any(marker in normalized_query for marker in BROAD_OUTAGE_MARKERS)
    return has_entity_marker and has_outage_marker


def _deduplicate_queries(queries: list[str]) -> list[str]:
    deduplicated_queries: list[str] = []
    seen_queries: set[str] = set()

    for query in queries:
        stripped_query = query.strip()
        normalized_query = _normalize_query(stripped_query)
        if not normalized_query or normalized_query in seen_queries:
            continue
        seen_queries.add(normalized_query)
        deduplicated_queries.append(stripped_query)

    return deduplicated_queries


def _normalize_query(query: str) -> str:
    normalized = unicodedata.normalize("NFKC", query).casefold()
    return WHITESPACE_RE.sub(" ", normalized).strip()

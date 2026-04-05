from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import re

from app.agent.memory import ConversationTurn
from app.agent.prompting import build_system_prompt
from app.agent.recommendation import RecommendationComposer
from app.agent.tools import (
    CATALOG_FILE_NAME,
    CatalogEntry,
    ReadFileTool,
    ToolCallRecord,
    ToolExecutionError,
    load_catalog_from_text,
)


MAX_FILE_READS = 2
SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")
SCENARIO_SPLIT_RE = re.compile(r"(?=场景[一二三四五六七八九十0-9]+[:：])")
SECTION_MARKERS_RE = re.compile(r"(?=[一二三四五六七八九十]+、)")
FOLLOW_UP_MARKERS = ("刚才", "刚刚", "那", "这个", "这种", "上一条", "前面")
LAST_FILES_MARKERS = ("哪些文件", "看了哪些", "读了哪些", "consulted files")
BOILERPLATE_MARKERS = (
    "文档编号",
    "版本",
    "最后更新",
    "适用范围",
    "值班职责",
    "值班工程师",
    "值班人员",
)
INTRO_MARKERS = (
    "负责保障",
    "第一道防线",
    "每周轮换",
    "交接时需确认",
    "每日",
    "巡检",
)
OPERATIONAL_KEYWORDS = (
    "检查",
    "确认",
    "排查",
    "处理",
    "恢复",
    "切换",
    "回滚",
    "重启",
    "监控",
    "线程",
    "复制",
    "延迟",
    "连接",
    "故障",
    "告警",
    "集群",
    "服务",
    "节点",
)
FOCUS_SECTION_MARKERS = (
    "场景",
    "处理步骤",
    "处置步骤",
    "排查步骤",
    "恢复步骤",
    "应急步骤",
    "响应流程",
    "升级流程",
)
ESCALATION_QUERY_MARKERS = (
    "升级",
    "上报",
    "通知",
    "p0",
    "p1",
    "p2",
    "阈值",
    "超过",
    "高于",
    "低于",
    "持续",
    "分钟",
    "秒",
    "严重",
    "高危",
)
ESCALATION_CONDITIONAL_MARKERS = (
    "如果",
    "若",
    "当",
    "一旦",
    "超过",
    "高于",
    "低于",
    "达到",
    "持续",
    "触发",
)
ESCALATION_CONTENT_MARKERS = (
    "升级",
    "上报",
    "通知",
    "war room",
    "p0",
    "p1",
    "p2",
    "负责人",
    "拉起",
)
THRESHOLD_CONTENT_MARKERS = (
    "超过",
    "高于",
    "低于",
    "达到",
    "持续",
    "分钟",
    "秒",
    "阈值",
    "%",
)
SYMPTOM_QUERY_MARKERS = (
    "oom",
    "内存",
    "memory",
    "rss",
    "heap",
    "堆",
    "kill",
    "killed",
    "重启",
    "restart",
    "泄漏",
    "leak",
)
SYMPTOM_CONTENT_MARKERS = (
    "oom",
    "内存",
    "memory",
    "rss",
    "heap",
    "堆",
    "kill",
    "killed",
    "重启",
    "restart",
    "泄漏",
    "leak",
    "大对象缓存",
)
ROUTING_STOP_TERMS = {
    "怎么",
    "怎么办",
    "怎么处理",
    "如何",
    "一下",
    "有人",
    "怀疑",
    "问题",
    "异常",
    "当前",
    "这个",
    "那个",
    "系统",
}
QUERY_EXPANSIONS = {
    "oom": ("oom", "内存溢出", "内存", "outofmemoryerror"),
    "主从": ("主从", "复制", "从库"),
    "复制": ("复制", "主从", "从库"),
    "入侵": ("入侵", "攻击", "恶意", "黑客", "安全事件"),
    "攻击": ("攻击", "入侵", "恶意", "黑客", "安全事件"),
    "推荐": ("推荐", "排序", "效果", "模型"),
    "质量下降": ("质量下降", "效果下降", "排序效果下降", "推荐质量"),
    "模型": ("模型", "推理", "效果"),
    "p0": ("p0", "故障分级", "响应流程", "升级", "事故"),
    "响应流程": ("响应流程", "升级", "通知", "故障分级"),
}
MULTI_FILE_MARKERS = ("p0", "响应流程", "升级", "事故", "war room")
LOW_CONFIDENCE_SCORE = 5.5
LOW_CONFIDENCE_GAP = 0.9
RECOMMENDATION_FEATURE_ENV = "AGENT_RECOMMENDATION_COMPOSER_ENABLED"
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AgentRunResult:
    assistant_message: str
    tool_calls: list[ToolCallRecord]
    consulted_files: list[str]


@dataclass(slots=True)
class RecentContext:
    last_consulted_files: list[str]


@dataclass(slots=True)
class RankedCatalogEntry:
    entry: CatalogEntry
    score: float
    signal_count: int


class AgentLoop:
    def __init__(
        self,
        *,
        read_file_tool: ReadFileTool,
        max_file_reads: int = MAX_FILE_READS,
    ) -> None:
        self._read_file_tool = read_file_tool
        self._max_file_reads = max_file_reads
        self._system_prompt = build_system_prompt()
        self._recommendation_enabled = _env_flag_enabled(RECOMMENDATION_FEATURE_ENV, default=True)
        self._recommendation_composer = RecommendationComposer(mode="rule_based")

    def run(self, message: str, *, history: list[ConversationTurn] | None = None) -> AgentRunResult:
        recent_context = _build_recent_context(history or [])

        tool_calls: list[ToolCallRecord] = []
        catalog_text = self._invoke_read_file(CATALOG_FILE_NAME, tool_calls)
        if catalog_text is None:
            return AgentRunResult(
                assistant_message="I could not read the SOP catalog, so I cannot answer safely yet.",
                tool_calls=tool_calls,
                consulted_files=[],
            )

        if _asks_about_last_files(message) and recent_context.last_consulted_files:
            return AgentRunResult(
                assistant_message=_build_last_files_answer(recent_context.last_consulted_files),
                tool_calls=tool_calls,
                consulted_files=[],
            )

        catalog_entries = load_catalog_from_text(catalog_text)
        ranked_entries = self._rank_catalog_entries(
            catalog_entries,
            message=message,
            previous_files=recent_context.last_consulted_files,
        )
        selected_files = self._select_files(ranked_entries, message=message)
        if not selected_files and ranked_entries:
            selected_files = [ranked_entries[0].entry.file_name]

        if not selected_files or _is_low_confidence(ranked_entries, message=message):
            return AgentRunResult(
                assistant_message=_build_clarification_answer(catalog_entries, ranked_entries),
                tool_calls=tool_calls,
                consulted_files=[],
            )

        consulted_files: list[str] = []
        consulted_payloads: dict[str, str] = {}
        for fname in selected_files:
            content = self._invoke_read_file(fname, tool_calls)
            if content is None:
                continue
            consulted_files.append(fname)
            consulted_payloads[fname] = content

        assistant_message = self._compose_answer(
            message=message,
            catalog_entries=catalog_entries,
            consulted_payloads=consulted_payloads,
        )
        return AgentRunResult(
            assistant_message=assistant_message,
            tool_calls=tool_calls,
            consulted_files=consulted_files,
        )

    def _invoke_read_file(self, fname: str, tool_calls: list[ToolCallRecord]) -> str | None:
        logger.info(
            "agent_tool_invocation",
            extra={
                "event": "agent_tool_invocation",
                "tool_name": "readFile",
                "fname": fname,
            },
        )
        try:
            result = self._read_file_tool.read_file(fname)
        except ToolExecutionError as exc:
            tool_calls.append(
                ToolCallRecord(
                    tool_name="readFile",
                    arguments={"fname": fname},
                    status="error",
                    output_preview=str(exc),
                )
            )
            return None

        tool_calls.append(
            ToolCallRecord(
                tool_name="readFile",
                arguments={"fname": fname},
                status="ok",
                output_preview=result.preview,
            )
        )
        return result.content

    def _rank_catalog_entries(
        self,
        catalog_entries: list[CatalogEntry],
        *,
        message: str,
        previous_files: list[str],
    ) -> list[RankedCatalogEntry]:
        routing_terms = _routing_terms(message)
        ranked_entries: list[RankedCatalogEntry] = []

        for entry in catalog_entries:
            score, signal_count = _score_catalog_entry(entry, routing_terms)
            if _is_follow_up_query(message) and entry.file_name in previous_files:
                score += 0.6
                signal_count += 1
            if score <= 0:
                continue
            ranked_entries.append(RankedCatalogEntry(entry=entry, score=score, signal_count=signal_count))

        ranked_entries.sort(key=lambda item: (-item.score, -item.signal_count, item.entry.file_name))
        return ranked_entries

    def _select_files(self, ranked_entries: list[RankedCatalogEntry], *, message: str) -> list[str]:
        if not ranked_entries:
            return []

        selected_files = [ranked_entries[0].entry.file_name]
        if len(ranked_entries) == 1:
            return selected_files

        second_entry = ranked_entries[1]
        top_entry = ranked_entries[0]
        allow_second_file = _is_multi_file_query(message) or (
            second_entry.score >= top_entry.score * 0.72 and second_entry.score >= LOW_CONFIDENCE_SCORE
        )
        if allow_second_file:
            selected_files.append(second_entry.entry.file_name)

        return selected_files[: self._max_file_reads]

    def _compose_answer(
        self,
        *,
        message: str,
        catalog_entries: list[CatalogEntry],
        consulted_payloads: dict[str, str],
    ) -> str:
        if not self._recommendation_enabled or not consulted_payloads:
            return self._compose_answer_legacy(
                message=message,
                catalog_entries=catalog_entries,
                consulted_payloads=consulted_payloads,
            )

        try:
            recommendation = self._recommendation_composer.compose(
                message=message,
                catalog_entries=catalog_entries,
                consulted_payloads=consulted_payloads,
            )
        except Exception:
            logger.exception(
                "recommendation_composer_failed",
                extra={
                    "event": "recommendation_composer_failed",
                    "mode": "rule_based",
                },
            )
            return self._compose_answer_legacy(
                message=message,
                catalog_entries=catalog_entries,
                consulted_payloads=consulted_payloads,
            )

        return recommendation.rendered_text

    def _compose_answer_legacy(
        self,
        *,
        message: str,
        catalog_entries: list[CatalogEntry],
        consulted_payloads: dict[str, str],
    ) -> str:
        _ = self._system_prompt

        if not consulted_payloads:
            available_titles = ", ".join(entry.title for entry in catalog_entries[:3])
            return (
                "建议处理方式\n"
                "- 目前还没有定位到足够相关的 SOP，请换一种更具体的故障描述再试一次。\n\n"
                "支持依据\n"
                f"- 当前目录中的示例包括：{available_titles}。\n\n"
                "参考 SOP\n"
                "- 当前轮次只读取了 `catalog.json`。"
            )

        catalog_by_file = {entry.file_name: entry for entry in catalog_entries}
        action_lines = ["建议处理方式"]
        evidence_lines = ["支持依据"]
        reference_lines = ["参考 SOP"]

        for file_name, content in consulted_payloads.items():
            entry = catalog_by_file.get(file_name)
            if entry is None:
                continue

            detail = _extract_grounded_detail(content, message=message)
            if not detail:
                detail = _best_catalog_support(entry, message=message)
            if not detail:
                detail = entry.summary

            action_lines.append(f"- {detail}")
            evidence_lines.append(f"- `{file_name}`（{entry.title}）")
            reference_lines.append(f"- `{file_name}`")

        return "\n\n".join(
            [
                "\n".join(action_lines),
                "\n".join(evidence_lines),
                "\n".join(reference_lines),
            ]
        )


def _env_flag_enabled(name: str, *, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().casefold() not in {"0", "false", "off", "no"}


def _build_recent_context(history: list[ConversationTurn]) -> RecentContext:
    for turn in reversed(history[-4:]):
        if turn.role == "assistant" and turn.consulted_files:
            return RecentContext(last_consulted_files=list(turn.consulted_files))
    return RecentContext(last_consulted_files=[])


def _routing_terms(message: str) -> list[str]:
    base_terms = _message_terms(message)
    routing_terms: list[str] = []
    seen_terms: set[str] = set()

    for term in base_terms:
        if term in ROUTING_STOP_TERMS:
            continue
        for variant in QUERY_EXPANSIONS.get(term, (term,)):
            cleaned = variant.casefold()
            if len(cleaned) < 2 or cleaned in ROUTING_STOP_TERMS or cleaned in seen_terms:
                continue
            seen_terms.add(cleaned)
            routing_terms.append(cleaned)

    return routing_terms[:36]


def _score_catalog_entry(entry: CatalogEntry, routing_terms: list[str]) -> tuple[float, int]:
    if not routing_terms:
        return 0.0, 0

    score = 0.0
    signal_count = 0
    title_text = f"{entry.title} {entry.team_or_domain}".casefold()
    headings_text = " ".join(entry.scenario_headings + entry.incident_themes).casefold()
    scenario_text = " ".join(entry.scenario_snippets).casefold()
    summary_text = entry.summary.casefold()
    keywords = {keyword.casefold() for keyword in entry.keywords}
    operational_terms = {term.casefold() for term in entry.operational_terms}
    escalation_terms = {term.casefold() for term in entry.escalation_terms}

    for term in routing_terms:
        term_weight = _routing_term_weight(term)
        if term in title_text:
            score += 3.0 * term_weight
            signal_count += 1
        if term in headings_text:
            score += 2.6 * term_weight
            signal_count += 1
        if term in scenario_text:
            score += 2.2 * term_weight
            signal_count += 1
        if term in summary_text:
            score += 1.7 * term_weight
            signal_count += 1
        if term in keywords:
            score += 1.5 * term_weight
            signal_count += 1
        if term in operational_terms:
            score += 1.2 * term_weight
            signal_count += 1
        if term in escalation_terms:
            score += 1.5 * term_weight
            signal_count += 1

    if entry.scenario_snippets:
        score += 0.3

    return score, signal_count


def _routing_term_weight(term: str) -> float:
    if re.fullmatch(r"[a-z0-9/_-]+", term):
        return 1.2 if len(term) >= 3 else 0.9
    if len(term) >= 5:
        return 1.2
    if len(term) == 4:
        return 1.0
    if len(term) == 3:
        return 0.8
    return 0.5


def _is_low_confidence(ranked_entries: list[RankedCatalogEntry], *, message: str) -> bool:
    if not ranked_entries:
        return True

    top_entry = ranked_entries[0]
    if top_entry.score < LOW_CONFIDENCE_SCORE or top_entry.signal_count < 2:
        return True

    if len(ranked_entries) == 1 or _is_multi_file_query(message):
        return False

    second_entry = ranked_entries[1]
    if top_entry.score - second_entry.score < LOW_CONFIDENCE_GAP and second_entry.score >= LOW_CONFIDENCE_SCORE:
        return True

    return False


def _build_clarification_answer(
    catalog_entries: list[CatalogEntry],
    ranked_entries: list[RankedCatalogEntry],
) -> str:
    if ranked_entries:
        top_titles = "、".join(entry.entry.team_or_domain for entry in ranked_entries[:4])
    else:
        top_titles = "数据库 DBA、后端服务、SRE 基础设施、安全团队、AI 算法"

    return (
        "建议处理方式\n"
        "- 这个问题目前还不够明确，我不想在没有读到足够相关 SOP 的情况下给出确定建议。\n\n"
        "支持依据\n"
        f"- 从目录里看，当前更接近的领域可能是：{top_titles}。请补充是数据库、后端、基础设施、安全，还是 AI/推荐相关问题。\n\n"
        "参考 SOP\n"
        "- 当前轮次只读取了 `catalog.json`。"
    )


def _best_catalog_support(entry: CatalogEntry, *, message: str) -> str:
    candidates = entry.scenario_snippets + entry.incident_themes + [entry.summary]
    routing_terms = _routing_terms(message)
    best_candidate = ""
    best_score = float("-inf")

    for candidate in candidates:
        candidate_text = candidate.strip()
        if not candidate_text:
            continue
        score = 0.0
        for term in routing_terms:
            if term in candidate_text.casefold():
                score += _routing_term_weight(term)
        if "场景" in candidate_text:
            score += 0.8
        if score > best_score:
            best_score = score
            best_candidate = candidate_text

    return _truncate(best_candidate, limit=200) if best_candidate else ""


def _extract_grounded_detail(content: str, *, message: str) -> str:
    _, _, visible_text = content.partition("\n\n")
    excerpt = visible_text or content
    candidates = _build_candidate_segments(excerpt)
    if not candidates:
        return ""

    message_terms = _message_terms(message)
    best_segment = ""
    best_score = float("-inf")

    for candidate in candidates:
        score = _score_candidate_segment(candidate, message_terms)
        if score > best_score:
            best_score = score
            best_segment = candidate

    if best_score <= 0:
        return ""
    return _truncate(best_segment, limit=200)


def _message_terms(message: str) -> list[str]:
    normalized = message.strip()
    terms: list[str] = []

    for token in re.findall(r"[A-Za-z0-9/_-]+", normalized):
        if len(token) >= 2:
            terms.append(token.casefold())

    for chunk in re.findall(r"[\u4e00-\u9fff0-9]+", normalized):
        if len(chunk) >= 2:
            terms.append(chunk)
        upper = min(len(chunk), 5)
        for size in range(2, upper + 1):
            for start in range(0, len(chunk) - size + 1):
                terms.append(chunk[start : start + size])

    deduplicated_terms: list[str] = []
    seen_terms: set[str] = set()
    for term in terms:
        if term in seen_terms:
            continue
        seen_terms.add(term)
        deduplicated_terms.append(term)

    return deduplicated_terms[:24]


def _build_candidate_segments(text: str) -> list[str]:
    normalized_text = " ".join(text.split())
    if not normalized_text:
        return []

    candidates: list[str] = []

    for segment in SCENARIO_SPLIT_RE.split(normalized_text):
        cleaned = segment.strip()
        if cleaned:
            candidates.append(cleaned)

    for segment in SECTION_MARKERS_RE.split(normalized_text):
        cleaned = segment.strip()
        if cleaned:
            candidates.append(cleaned)

    sentences = [match.strip() for match in SENTENCE_RE.findall(normalized_text) if match.strip()]
    candidates.extend(sentences)
    for index in range(len(sentences) - 1):
        candidates.append(f"{sentences[index]} {sentences[index + 1]}")

    deduplicated_candidates: list[str] = []
    seen_candidates: set[str] = set()
    for candidate in candidates:
        compact = candidate.strip()
        if len(compact) < 8 or compact in seen_candidates:
            continue
        seen_candidates.add(compact)
        deduplicated_candidates.append(compact)

    return deduplicated_candidates


def _score_candidate_segment(segment: str, message_terms: list[str]) -> float:
    score = 0.0
    compact_segment = segment.lstrip()
    lowered_segment = segment.casefold()
    lowered_compact_segment = compact_segment.casefold()

    if any(marker in segment for marker in BOILERPLATE_MARKERS):
        score -= 6.0
    if any(marker in segment for marker in INTRO_MARKERS):
        score -= 2.5
    if segment.startswith(("一、值班职责", "二、监控指标", "四、升级流程", "五、禁止操作", "六、工具与命令参考")):
        score -= 4.0

    if "场景" in segment:
        score += 2.5
    if compact_segment.startswith(FOCUS_SECTION_MARKERS):
        score += 1.0
    elif any(marker in segment for marker in FOCUS_SECTION_MARKERS):
        score -= 0.8

    if _message_prefers_escalation_detail(message_terms):
        if lowered_compact_segment.startswith(ESCALATION_CONDITIONAL_MARKERS):
            score += 3.0
        elif any(marker in lowered_segment for marker in ESCALATION_CONDITIONAL_MARKERS):
            score -= 1.0
        if any(marker in lowered_segment for marker in ESCALATION_CONTENT_MARKERS):
            score += 1.0
        if any(marker in lowered_segment for marker in THRESHOLD_CONTENT_MARKERS):
            score += 0.8

    if _message_prefers_symptom_detail(message_terms):
        symptom_index = _first_marker_index(lowered_segment, SYMPTOM_CONTENT_MARKERS)
        if symptom_index >= 0:
            score += 1.2
            if symptom_index <= 12:
                score += 4.0
            elif any(marker in segment[:symptom_index] for marker in ("。", "；", ";")):
                score -= 2.0

    for term in message_terms:
        if term in segment:
            score += 1.2 + min(len(term), 4) * 0.4

    for keyword in OPERATIONAL_KEYWORDS:
        if keyword in segment:
            score += 0.35

    if len(segment) > 320:
        score -= 0.5

    return score


def _message_prefers_escalation_detail(message_terms: list[str]) -> bool:
    joined_terms = " ".join(message_terms).casefold()
    return any(marker in joined_terms for marker in ESCALATION_QUERY_MARKERS)


def _message_prefers_symptom_detail(message_terms: list[str]) -> bool:
    joined_terms = " ".join(message_terms).casefold()
    return any(marker in joined_terms for marker in SYMPTOM_QUERY_MARKERS)


def _first_marker_index(text: str, markers: tuple[str, ...]) -> int:
    indexes = [text.find(marker) for marker in markers if text.find(marker) >= 0]
    if not indexes:
        return -1
    return min(indexes)


def _truncate(text: str, *, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _asks_about_last_files(message: str) -> bool:
    return any(marker in message for marker in LAST_FILES_MARKERS)


def _is_follow_up_query(message: str) -> bool:
    return any(marker in message for marker in FOLLOW_UP_MARKERS)


def _is_multi_file_query(message: str) -> bool:
    lowered = message.casefold()
    return any(marker in lowered for marker in MULTI_FILE_MARKERS)


def _build_last_files_answer(consulted_files: list[str]) -> str:
    reference_lines = ["上次参考 SOP"]
    for file_name in consulted_files:
        reference_lines.append(f"- `{file_name}`")
    return "\n".join(reference_lines)

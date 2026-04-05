from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import json
import logging
import re

from app.agent.tools import CatalogEntry
from app.observability.metrics import (
    record_recommendation_quality,
    record_rewrite_trigger,
)


MAX_CONTIGUOUS_COPY_CHARS = 20
SIMILARITY_REWRITE_THRESHOLD = 0.38
SCENARIO_SPLIT_RE = re.compile(r"(?=场景[一二三四五六七八九十0-9]+[:：])")
SECTION_SPLIT_RE = re.compile(r"(?=[一二三四五六七八九十]+、)")
SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")
ACTION_HINTS = (
    "检查",
    "确认",
    "排查",
    "处理",
    "恢复",
    "回滚",
    "降级",
    "重启",
    "通知",
    "拉起",
    "隔离",
    "保全",
    "轮换",
    "升级",
    "导出",
    "冻结",
)
SYNONYM_REWRITES = (
    ("先检查", "先核查"),
    ("检查", "核查"),
    ("确认", "判断"),
    ("最近发布记录", "最近一次发布记录"),
)
PHRASE_REWRITES = (
    ("实例内存使用", "实例内存"),
    ("最近一次发布记录", "最近发布"),
    ("复制线程状态", "复制线程"),
    ("binlog 积压情况", "binlog 积压"),
    ("慢查询或大事务阻塞复制", "慢查询/大事务阻塞"),
    ("特征新鲜度", "特征时效"),
    ("排序效果监控", "排序监控"),
    ("线上实验配置", "实验配置"),
    ("高风险凭证", "高危凭证"),
    ("是否存在", "是否有"),
    ("通知业务负责人并冻结变更", "先通知业务负责人，并立即冻结变更"),
    ("准备回滚或降级方案", "同时备好回滚/降级方案"),
    ("立即隔离主机", "先隔离主机"),
    ("保全证据", "保留证据"),
)
QUALITY_SNAPSHOT_HEADERS = (
    "建议处理方式",
    "结论",
    "行动计划",
    "优先级与判断依据",
    "风险与副作用",
    "回滚/缓解",
    "升级条件",
    "置信度与缺失信息",
    "支持依据",
    "参考 SOP",
)
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RecommendationEvidence:
    file_name: str
    title: str
    excerpt: str
    relevance_score: float
    recency_score: float
    source_quality_score: float

    @property
    def ranking_score(self) -> float:
        return self.relevance_score * 0.65 + self.source_quality_score * 0.25 + self.recency_score * 0.10


@dataclass(slots=True)
class SupportingEvidence:
    file_name: str
    title: str
    reason: str


@dataclass(slots=True)
class RecommendationContent:
    decision_summary: list[str]
    action_plan: list[str]
    priority_and_severity_rationale: str
    risks_and_side_effects: list[str]
    rollback_and_mitigation: list[str]
    escalation_conditions: list[str]
    confidence_and_missing_information: str
    supporting_evidence: list[SupportingEvidence]


@dataclass(slots=True)
class RecommendationQuality:
    actionability_score: float
    specificity_score: float
    evidence_coverage_score: float
    duplication_score: float
    rewrite_triggered: bool = False


@dataclass(slots=True)
class RecommendationResult:
    content: RecommendationContent
    rendered_text: str
    quality: RecommendationQuality
    evidence: list[RecommendationEvidence]


class RecommendationComposer:
    def __init__(self, *, mode: str) -> None:
        self._mode = mode

    def compose(
        self,
        *,
        message: str,
        catalog_entries: list[CatalogEntry],
        consulted_payloads: dict[str, str],
    ) -> RecommendationResult:
        evidence = _rank_evidence(
            message=message,
            catalog_entries=catalog_entries,
            consulted_payloads=consulted_payloads,
        )
        content = _build_recommendation_content(message=message, evidence=evidence)
        rendered_text = render_recommendation_text(content)
        return self._finalize(content=content, rendered_text=rendered_text, evidence=evidence)

    def finalize_llm_output(
        self,
        *,
        raw_output: str,
        consulted_payloads: dict[str, str],
        consulted_files: list[str],
    ) -> RecommendationResult:
        content = parse_llm_recommendation_content(raw_output, consulted_files=consulted_files)
        evidence = _evidence_from_payloads(consulted_payloads)
        if content is None:
            content = RecommendationContent(
                decision_summary=["当前建议来自模型输出，但没有成功解析成结构化结果。"],
                action_plan=[raw_output.strip() or "当前没有拿到可用的结构化建议，请改用规则回退结果。"],
                priority_and_severity_rationale="当前无法从结构化输出中恢复优先级判断，建议人工复核。",
                risks_and_side_effects=["模型输出未结构化，可能存在表达冗余或依据不完整的问题。"],
                rollback_and_mitigation=["如结果质量不稳定，可通过特性开关切回规则推荐器。"],
                escalation_conditions=["如果模型输出与已读 SOP 明显不一致，请立即人工复核并升级。"],
                confidence_and_missing_information="置信度：低。缺少可解析的结构化字段，需要人工补充校验。",
                supporting_evidence=_supporting_evidence_from_evidence(evidence),
            )
            rendered_text = render_recommendation_text(content)
        else:
            rendered_text = extract_llm_rendered_text(raw_output) or render_recommendation_text(content)

        return self._finalize(content=content, rendered_text=rendered_text, evidence=evidence)

    def _finalize(
        self,
        *,
        content: RecommendationContent,
        rendered_text: str,
        evidence: list[RecommendationEvidence],
    ) -> RecommendationResult:
        quality = score_recommendation(
            rendered_text=rendered_text,
            content=content,
            evidence=evidence,
        )

        if quality.duplication_score >= SIMILARITY_REWRITE_THRESHOLD:
            rewritten_content = _rewrite_content(content)
            rewritten_text = render_recommendation_text(rewritten_content)
            rewritten_quality = score_recommendation(
                rendered_text=rewritten_text,
                content=rewritten_content,
                evidence=evidence,
            )
            rewritten_quality.rewrite_triggered = True
            record_rewrite_trigger(mode=self._mode, reason="high_similarity")
            logger.info(
                "recommendation_rewrite_triggered",
                extra={
                    "event": "recommendation_rewrite_triggered",
                    "mode": self._mode,
                    "duplication_score": round(quality.duplication_score, 4),
                },
            )
            if rewritten_quality.duplication_score <= quality.duplication_score:
                content = rewritten_content
                rendered_text = rewritten_text
                quality = rewritten_quality

        record_recommendation_quality(mode=self._mode, quality=quality)
        logger.info(
            "recommendation_quality",
            extra={
                "event": "recommendation_quality",
                "mode": self._mode,
                "actionability_score": round(quality.actionability_score, 4),
                "specificity_score": round(quality.specificity_score, 4),
                "evidence_coverage_score": round(quality.evidence_coverage_score, 4),
                "duplication_score": round(quality.duplication_score, 4),
                "rewrite_triggered": quality.rewrite_triggered,
            },
        )
        return RecommendationResult(
            content=content,
            rendered_text=rendered_text,
            quality=quality,
            evidence=evidence,
        )


def render_recommendation_text(content: RecommendationContent) -> str:
    lines = ["建议处理方式", "结论"]
    lines.extend(f"- {item}" for item in content.decision_summary)
    lines.append("")
    lines.append("行动计划")
    lines.extend(f"{index}. {step}" for index, step in enumerate(content.action_plan, start=1))
    lines.append("")
    lines.append("优先级与判断依据")
    lines.append(f"- {content.priority_and_severity_rationale}")
    lines.append("")
    lines.append("风险与副作用")
    lines.extend(f"- {item}" for item in content.risks_and_side_effects)
    lines.append("")
    lines.append("回滚/缓解")
    lines.extend(f"- {item}" for item in content.rollback_and_mitigation)
    lines.append("")
    lines.append("升级条件")
    lines.extend(f"- {item}" for item in content.escalation_conditions)
    lines.append("")
    lines.append("置信度与缺失信息")
    lines.append(f"- {content.confidence_and_missing_information}")
    lines.append("")
    lines.append("支持依据")
    lines.extend(
        f"- `{item.file_name}`（{item.title}）：{item.reason}"
        for item in content.supporting_evidence
    )
    lines.append("")
    lines.append("参考 SOP")
    lines.extend(f"- `{item.file_name}`" for item in content.supporting_evidence)
    return "\n".join(lines)


def parse_llm_recommendation_content(
    raw_output: str,
    *,
    consulted_files: list[str],
) -> RecommendationContent | None:
    payload = _extract_json_payload(raw_output)
    if payload is None:
        return None

    supporting_evidence_payload = payload.get("supporting_evidence")
    supporting_evidence = [
        SupportingEvidence(
            file_name=str(item.get("file", "")),
            title=str(item.get("title", "")),
            reason=str(item.get("reason", "")),
        )
        for item in supporting_evidence_payload
        if isinstance(item, dict) and item.get("file")
    ] if isinstance(supporting_evidence_payload, list) else []
    if not supporting_evidence:
        supporting_evidence = [
            SupportingEvidence(file_name=file_name, title=file_name, reason="模型引用了该文件作为依据。")
            for file_name in consulted_files
        ]

    return RecommendationContent(
        decision_summary=_coerce_list(payload.get("decision_summary"), fallback="当前已生成结构化结论。"),
        action_plan=_coerce_list(payload.get("action_plan"), fallback="请按当前已读 SOP 先完成一轮核查。"),
        priority_and_severity_rationale=str(
            payload.get("priority_and_severity_rationale", "当前缺少明确的优先级说明。")
        ),
        risks_and_side_effects=_coerce_list(
            payload.get("risks_and_side_effects"),
            fallback="执行高影响动作前，请先确认影响面和依赖方。",
        ),
        rollback_and_mitigation=_coerce_list(
            payload.get("rollback_and_mitigation"),
            fallback="如首轮动作无效，优先回到低风险缓解路径并人工复核。",
        ),
        escalation_conditions=_coerce_list(
            payload.get("escalation_conditions"),
            fallback="如果影响面扩大或需要跨团队配合，请立即升级。",
        ),
        confidence_and_missing_information=str(
            payload.get("confidence_and_missing_information", "置信度：中。仍需补充影响面和实时指标。")
        ),
        supporting_evidence=supporting_evidence,
    )


def extract_llm_rendered_text(raw_output: str) -> str:
    if "TEXT:" in raw_output:
        _, _, text_block = raw_output.partition("TEXT:")
        return text_block.strip()
    return raw_output.strip()


def score_recommendation(
    *,
    rendered_text: str,
    content: RecommendationContent,
    evidence: list[RecommendationEvidence],
) -> RecommendationQuality:
    actionability_score = min(1.0, 0.35 + len(content.action_plan) * 0.15 + len(content.rollback_and_mitigation) * 0.08)
    specificity_signals = sum(
        bool(re.search(pattern, rendered_text))
        for pattern in (r"\d", r"P[0-2]", r"OOM", r"war room", r"主从", r"延迟", r"实例", r"负责人")
    )
    specificity_score = min(1.0, 0.3 + specificity_signals * 0.1)
    evidence_coverage_score = min(
        1.0,
        0.25 + min(len(content.supporting_evidence), 3) * 0.2 + min(len(evidence), 3) * 0.1,
    )
    duplication_score = measure_duplication_score(rendered_text, [item.excerpt for item in evidence])
    return RecommendationQuality(
        actionability_score=actionability_score,
        specificity_score=specificity_score,
        evidence_coverage_score=evidence_coverage_score,
        duplication_score=duplication_score,
    )


def measure_duplication_score(text: str, evidence_texts: list[str]) -> float:
    normalized_text = _normalize_text(text)
    if not normalized_text or not evidence_texts:
        return 0.0

    scores: list[float] = []
    for evidence_text in evidence_texts:
        normalized_evidence = _normalize_text(evidence_text)
        if not normalized_evidence:
            continue
        similarity_ratio = SequenceMatcher(None, normalized_text, normalized_evidence).ratio()
        longest_overlap = SequenceMatcher(None, normalized_text, normalized_evidence).find_longest_match(
            0,
            len(normalized_text),
            0,
            len(normalized_evidence),
        ).size
        overlap_ratio = longest_overlap / max(1, min(len(normalized_text), len(normalized_evidence)))
        copy_penalty = 1.0 if longest_overlap >= MAX_CONTIGUOUS_COPY_CHARS else 0.0
        scores.append(max(similarity_ratio, overlap_ratio, copy_penalty))

    return max(scores, default=0.0)


def has_large_verbatim_overlap(text: str, evidence_texts: list[str], *, threshold: int = MAX_CONTIGUOUS_COPY_CHARS) -> bool:
    normalized_text = _normalize_text(text)
    for evidence_text in evidence_texts:
        normalized_evidence = _normalize_text(evidence_text)
        if not normalized_evidence:
            continue
        longest_overlap = SequenceMatcher(None, normalized_text, normalized_evidence).find_longest_match(
            0,
            len(normalized_text),
            0,
            len(normalized_evidence),
        ).size
        if longest_overlap >= threshold:
            return True
    return False


def _build_recommendation_content(
    *,
    message: str,
    evidence: list[RecommendationEvidence],
) -> RecommendationContent:
    top_evidence = evidence[:3]
    action_plan = _build_action_plan(message=message, evidence=top_evidence)
    priority = _priority_and_rationale(message=message, evidence=top_evidence)
    risks = _risks_and_side_effects(evidence=top_evidence)
    rollback = _rollback_and_mitigation(evidence=top_evidence)
    escalation = _escalation_conditions(message=message, evidence=top_evidence)
    confidence = _confidence_and_missing_information(message=message, evidence=top_evidence)
    return RecommendationContent(
        decision_summary=_decision_summary(message=message, evidence=top_evidence, action_plan=action_plan),
        action_plan=action_plan,
        priority_and_severity_rationale=priority,
        risks_and_side_effects=risks,
        rollback_and_mitigation=rollback,
        escalation_conditions=escalation,
        confidence_and_missing_information=confidence,
        supporting_evidence=_supporting_evidence_from_evidence(top_evidence),
    )


def _rank_evidence(
    *,
    message: str,
    catalog_entries: list[CatalogEntry],
    consulted_payloads: dict[str, str],
) -> list[RecommendationEvidence]:
    catalog_by_file = {entry.file_name: entry for entry in catalog_entries}
    message_terms = _message_terms(message)
    evidence: list[RecommendationEvidence] = []

    for file_name, content in consulted_payloads.items():
        entry = catalog_by_file.get(file_name)
        title = entry.title if entry is not None else file_name
        best_excerpt = ""
        best_score = float("-inf")
        best_quality = 0.0

        for candidate in _candidate_segments(content):
            relevance_score = _segment_relevance(candidate, message_terms)
            quality_score = _source_quality(candidate)
            ranking_score = relevance_score * 0.65 + quality_score * 0.25 + 0.05
            if ranking_score > best_score:
                best_score = ranking_score
                best_excerpt = candidate
                best_quality = quality_score

        if best_excerpt:
            evidence.append(
                RecommendationEvidence(
                    file_name=file_name,
                    title=title,
                    excerpt=_truncate(best_excerpt, limit=160),
                    relevance_score=max(best_score, 0.0),
                    recency_score=0.5,
                    source_quality_score=best_quality,
                )
            )

    evidence.sort(key=lambda item: (-item.ranking_score, item.file_name))
    return evidence


def _evidence_from_payloads(consulted_payloads: dict[str, str]) -> list[RecommendationEvidence]:
    evidence: list[RecommendationEvidence] = []
    for file_name, content in consulted_payloads.items():
        evidence.append(
            RecommendationEvidence(
                file_name=file_name,
                title=file_name,
                excerpt=_truncate(_visible_text(content), limit=160),
                relevance_score=0.6,
                recency_score=0.5,
                source_quality_score=0.5,
            )
        )
    return evidence


def _decision_summary(
    *,
    message: str,
    evidence: list[RecommendationEvidence],
    action_plan: list[str],
) -> list[str]:
    incident_label = _incident_label(message=message, evidence=evidence)
    priority = "高优先级"
    if any(marker in message.casefold() for marker in ("p0", "攻击", "入侵")):
        priority = "最高优先级"
    summary = [f"当前更像是{incident_label}，建议按{priority}先控风险、再做定位。"]
    if action_plan:
        summary.append(f"第一步先做 {action_plan[0]}；后续再按证据推进后续动作。")
    return summary


def _build_action_plan(*, message: str, evidence: list[RecommendationEvidence]) -> list[str]:
    steps: list[str] = []
    seen_steps: set[str] = set()

    for item in evidence:
        for clause in _action_clauses(item.excerpt):
            rewritten = _rewrite_clause(clause)
            if len(rewritten) < 4 or rewritten in seen_steps:
                continue
            seen_steps.add(rewritten)
            steps.append(rewritten)
            if len(steps) >= 4:
                break
        if len(steps) >= 4:
            break

    if not steps:
        steps.append("先基于当前已读 SOP 做一轮影响面确认，再决定是否执行高影响动作。")

    if len(steps) == 1:
        steps.append("把关键症状、影响范围和最近变更补齐后，再决定是否需要升级或回退。")

    return steps[:4]


def _priority_and_rationale(*, message: str, evidence: list[RecommendationEvidence]) -> str:
    lowered = message.casefold()
    if any(marker in lowered for marker in ("p0", "攻击", "入侵")):
        return "该问题带有安全或最高等级事故信号，处理优先级应高于普通功能故障。"
    if any(marker in lowered for marker in ("oom", "主从", "延迟", "错误率", "白屏")):
        return "该问题会直接影响核心服务可用性或数据一致性，建议按高优先级处置。"
    if evidence:
        return f"当前主要依据 `{evidence[0].file_name}` 的场景化处置内容判断优先级。"
    return "当前证据不足，建议先补齐影响面和实时指标再定级。"


def _risks_and_side_effects(*, evidence: list[RecommendationEvidence]) -> list[str]:
    joined = " ".join(item.excerpt for item in evidence)
    risks: list[str] = []
    if "重启" in joined:
        risks.append("直接重启可能掩盖现场，执行前应先保留必要诊断信息。")
    if "隔离" in joined:
        risks.append("隔离动作会影响对应主机或账号的可用性，需要先确认影响范围。")
    if "回滚" in joined or "降级" in joined:
        risks.append("回退或降级可能牺牲部分功能，需要同步业务方并明确影响窗口。")
    if not risks:
        risks.append("当前 SOP 没有给出更细的副作用说明，执行高影响动作前请先确认依赖方和影响面。")
    return risks[:3]


def _rollback_and_mitigation(*, evidence: list[RecommendationEvidence]) -> list[str]:
    joined = " ".join(item.excerpt for item in evidence)
    mitigations: list[str] = []
    if "回滚" in joined:
        mitigations.append("如果故障与最近变更高度相关，优先准备回退到上一稳定版本。")
    if "降级" in joined:
        mitigations.append("若核心链路无法快速恢复，优先启用降级路径稳住主流程。")
    if "隔离" in joined:
        mitigations.append("若采取隔离措施，优先把范围收敛到受影响主机或账号，避免扩大影响。")
    if not mitigations:
        mitigations.append("如果首轮动作无效，先保留现场、暂停额外高风险变更，并回看最近配置或发布。")
    return mitigations[:3]


def _escalation_conditions(*, message: str, evidence: list[RecommendationEvidence]) -> list[str]:
    conditions: list[str] = []
    for item in evidence:
        excerpt_lowered = item.excerpt.casefold()
        if any(marker in excerpt_lowered for marker in ("p0", "p1", "war room", "通知", "升级", "持续", "分钟")):
            clauses = [
                _rewrite_clause(clause)
                for clause in _action_clauses(item.excerpt)
                if any(
                    marker in clause.casefold()
                    for marker in ("p0", "p1", "war room", "通知", "升级", "持续", "分钟")
                )
            ]
            conditions.extend(clauses[:2])
    if not conditions:
        if any(marker in message.casefold() for marker in ("入侵", "攻击", "p0", "错误率", "延迟")):
            conditions.append("如果影响面扩大、持续时间超出阈值，或需要跨团队配合，请立即升级处理。")
        else:
            conditions.append("如果现有动作无法在短时间内止血，或需要跨团队协调，请尽快升级。")
    return _dedupe(conditions)[:3]


def _confidence_and_missing_information(*, message: str, evidence: list[RecommendationEvidence]) -> str:
    if len(evidence) >= 2:
        confidence = "中高"
    elif evidence:
        confidence = "中"
    else:
        confidence = "低"

    missing_info = _missing_information(message)
    return f"置信度：{confidence}。还缺少：{'、'.join(missing_info)}。"


def _supporting_evidence_from_evidence(evidence: list[RecommendationEvidence]) -> list[SupportingEvidence]:
    items: list[SupportingEvidence] = []
    for item in evidence[:3]:
        items.append(
            SupportingEvidence(
                file_name=item.file_name,
                title=item.title,
                reason=_evidence_reason(item.excerpt),
            )
        )
    return items


def _rewrite_content(content: RecommendationContent) -> RecommendationContent:
    return RecommendationContent(
        decision_summary=[_rewrite_clause(item) for item in content.decision_summary],
        action_plan=[_rewrite_clause(item) for item in content.action_plan],
        priority_and_severity_rationale=_rewrite_clause(content.priority_and_severity_rationale),
        risks_and_side_effects=[_rewrite_clause(item) for item in content.risks_and_side_effects],
        rollback_and_mitigation=[_rewrite_clause(item) for item in content.rollback_and_mitigation],
        escalation_conditions=[_rewrite_clause(item) for item in content.escalation_conditions],
        confidence_and_missing_information=_rewrite_clause(content.confidence_and_missing_information),
        supporting_evidence=[
            SupportingEvidence(
                file_name=item.file_name,
                title=item.title,
                reason=_rewrite_clause(item.reason),
            )
            for item in content.supporting_evidence
        ],
    )


def _rewrite_clause(text: str) -> str:
    rewritten = text.strip().strip("。")
    for source, target in SYNONYM_REWRITES:
        rewritten = rewritten.replace(source, target)
    for source, target in PHRASE_REWRITES:
        rewritten = rewritten.replace(source, target)
    rewritten = rewritten.replace("如果", "若").replace("再确认", "随后判断")
    rewritten = re.sub(r"\s+", " ", rewritten)
    return _truncate(rewritten, limit=80)


def _action_clauses(text: str) -> list[str]:
    cleaned = re.sub(r"场景[一二三四五六七八九十0-9]+[:：]", "", text)
    cleaned = cleaned.replace("处理步骤：", "").replace("处置步骤：", "").replace("排查步骤：", "")
    normalized = re.sub(r"\s*(\d+[.、])\s*", r"\n\1 ", cleaned)
    raw_clauses = re.split(r"[。；;]|，再|，并|，同时|,再|,并|,同时|, then|\n", normalized)
    clauses: list[str] = []
    for clause in raw_clauses:
        compact = re.sub(r"^\d+[.、]\s*", "", clause).strip("：: ，,")
        compact = re.sub(r"^(.{2,20})\s+\1", r"\1", compact)
        compact = re.sub(r"^.{2,20}时[,:，]\s*", "", compact)
        if len(compact) < 4:
            continue
        if re.fullmatch(r".*(响应流程|处理步骤|处置步骤|排查步骤)$", compact):
            continue
        comma_split = [item.strip() for item in re.split(r"[，,]", compact) if item.strip()]
        action_like_parts = [
            item
            for item in comma_split
            if any(keyword in item for keyword in ACTION_HINTS)
        ]
        if len(action_like_parts) >= 2 and len(action_like_parts) == len(comma_split):
            clauses.extend(action_like_parts)
            continue
        if any(keyword in compact for keyword in ACTION_HINTS) or re.search(r"\d", compact):
            clauses.append(compact)
    return clauses


def _evidence_reason(excerpt: str) -> str:
    clauses = [_rewrite_clause(item) for item in _action_clauses(excerpt)]
    if clauses:
        summary = "；".join(clauses[:2])
        return _truncate(f"该 SOP 明确要求优先执行：{summary}", limit=72)
    return _truncate(f"该 SOP 的场景处置重点是：{_rewrite_clause(excerpt)}", limit=72)


def _candidate_segments(content: str) -> list[str]:
    visible_text = _visible_text(content)
    normalized_text = " ".join(visible_text.split())
    if not normalized_text:
        return []

    candidates: list[str] = []
    candidates.extend(segment.strip() for segment in SCENARIO_SPLIT_RE.split(normalized_text) if segment.strip())
    candidates.extend(segment.strip() for segment in SECTION_SPLIT_RE.split(normalized_text) if segment.strip())
    candidates.extend(sentence.strip() for sentence in SENTENCE_RE.findall(normalized_text) if sentence.strip())

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        compact = candidate.strip()
        if len(compact) < 8 or compact in seen:
            continue
        seen.add(compact)
        deduped.append(compact)
    return deduped


def _segment_relevance(segment: str, message_terms: list[str]) -> float:
    lowered = segment.casefold()
    score = 0.0
    for term in message_terms:
        if term in lowered or term in segment:
            score += 1.1 + min(len(term), 4) * 0.25
    if "场景" in segment:
        score += 1.2
    if any(keyword in segment for keyword in ACTION_HINTS):
        score += 0.8
    if any(marker in lowered for marker in ("p0", "p1", "war room", "分钟", "超过")):
        score += 0.6
    return score


def _source_quality(segment: str) -> float:
    score = 0.4
    if "场景" in segment or "处理步骤" in segment:
        score += 0.3
    if any(keyword in segment for keyword in ACTION_HINTS):
        score += 0.2
    if len(segment) > 180:
        score -= 0.1
    return max(0.0, min(score, 1.0))


def _message_terms(message: str) -> list[str]:
    terms: list[str] = []
    lowered = message.casefold()
    terms.extend(token for token in re.findall(r"[a-z0-9/_-]{2,}", lowered))
    for chunk in re.findall(r"[\u4e00-\u9fff0-9]+", message):
        if len(chunk) >= 2:
            terms.append(chunk)
        for size in range(2, min(len(chunk), 5) + 1):
            for start in range(0, len(chunk) - size + 1):
                terms.append(chunk[start : start + size])
    return _dedupe(terms)[:24]


def _incident_label(*, message: str, evidence: list[RecommendationEvidence]) -> str:
    lowered = message.casefold()
    if "oom" in lowered:
        return "服务 OOM / 内存打满故障"
    if "主从" in message or "复制" in message:
        return "数据库复制延迟故障"
    if "入侵" in message or "攻击" in message:
        return "安全入侵/攻击事件"
    if "质量下降" in message or "推荐" in message:
        return "推荐效果退化事件"
    if evidence:
        return evidence[0].title.replace("On-Call SOP", "").strip(" -")
    return "当前值班事件"


def _missing_information(message: str) -> list[str]:
    lowered = message.casefold()
    if "oom" in lowered:
        return ["实例内存曲线", "最近发布记录", "异常流量情况"]
    if "主从" in message or "复制" in message:
        return ["复制线程状态", "binlog 积压", "慢查询或大事务情况"]
    if "入侵" in message or "攻击" in message:
        return ["受影响主机范围", "攻击入口", "凭证暴露面"]
    if "推荐" in message or "质量下降" in message:
        return ["异常开始时间", "模型/特征版本", "受影响流量比例"]
    return ["影响范围", "实时指标", "最近变更记录"]


def _extract_json_payload(raw_output: str) -> dict[str, object] | None:
    if "JSON:" not in raw_output:
        return None
    _, _, remainder = raw_output.partition("JSON:")
    json_block, _, _ = remainder.partition("TEXT:")
    candidate = json_block.strip()
    if not candidate:
        return None
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _coerce_list(value: object, *, fallback: str) -> list[str]:
    if isinstance(value, list):
        coerced = [str(item).strip() for item in value if str(item).strip()]
        if coerced:
            return coerced[:4]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return [fallback]


def _visible_text(content: str) -> str:
    _, _, visible_text = content.partition("\n\n")
    return visible_text or content


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def _truncate(text: str, *, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _dedupe(items: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        compact = item.strip()
        if not compact or compact in seen:
            continue
        seen.add(compact)
        deduped.append(compact)
    return deduped

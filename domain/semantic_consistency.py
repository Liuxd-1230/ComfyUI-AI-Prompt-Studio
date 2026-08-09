"""Deterministic semantics, risk-triggered criticism, and bounded repair."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Generic, Protocol, TypeVar

from ..schemas.anima import AnimaPromptPlan
from ..schemas.changeset import ChangeSet, InvalidatedFact, SemanticChange
from ..schemas.h3 import H3PromptPlan
from ..schemas.semantic import ConsistencyResult, RiskAssessment, SemanticIssue
from .plan_adapters import PlanAdapter


PlanT = TypeVar("PlanT")


class SemanticCritic(Protocol[PlanT]):
    def __call__(self, plan: PlanT, changeset: ChangeSet) -> list[SemanticIssue]: ...


Repairer = Callable[[PlanT, list[SemanticIssue]], PlanT]
Validator = Callable[[PlanT], list[SemanticIssue]]


HIGH_RISK_TOKENS = (
    "required_traits", "character_id", "characters", "subjects", "assets",
    "references", "retention", "dialogues", "speaker", "shots", "duration",
)
MEDIUM_RISK_TOKENS = ("environment", "lighting", "composition", "camera", "action")


def assess_risk(changeset: ChangeSet) -> RiskAssessment:
    score = 0
    reasons: list[str] = []
    for change in changeset.all_changes():
        if any(token in change.path for token in HIGH_RISK_TOKENS):
            score += 3
            reasons.append(f"高影响语义路径: {change.path}")
        elif any(token in change.path for token in MEDIUM_RISK_TOKENS):
            score += 1
            reasons.append(f"关联语义路径: {change.path}")
    if changeset.dependent_changes:
        score += 1
        reasons.append("包含依赖闭包变更")
    if changeset.invalidated_facts:
        score += 2
        reasons.append("存在失效事实")
    if changeset.constraint_conflicts:
        score += 4
        reasons.append("存在约束冲突")
    level = "high" if score >= 3 else "medium" if score else "low"
    return RiskAssessment(level=level, score=score, reasons=_dedupe(reasons),
                          critic_required=level == "high")


def analyze_anima_impacts(plan: AnimaPromptPlan,
                          changeset: ChangeSet) -> ChangeSet:
    """Add the minimum known dependency closure for ANIMA normal form."""
    existing = {change.path for change in changeset.all_changes()}
    for change in list(changeset.all_changes()):
        if change.path == "environment" and plan.lighting:
            if "lighting" not in existing:
                changeset.invalidated_facts.append(InvalidatedFact(
                    path="lighting",
                    reason="环境变化可能使原光线来源与时间条件失效；必须确认或同步更新"))
    return changeset


class SemanticConsistencyPipeline(Generic[PlanT]):
    """Run deterministic checks; invoke critic only for high risk; repair once."""

    def __init__(self, adapter: PlanAdapter[PlanT], validator: Validator[PlanT]) -> None:
        self.adapter = adapter
        self.validator = validator

    def run(self, plan: PlanT, changeset: ChangeSet, *,
            critic: SemanticCritic[PlanT] | None = None,
            repairer: Repairer[PlanT] | None = None) -> ConsistencyResult:
        candidate = self.adapter.normalize(self.adapter.clone(plan))
        risk = assess_risk(changeset)
        issues = self.validator(candidate)
        critic_invoked = False
        if risk.critic_required and critic is not None:
            issues.extend(critic(candidate, changeset))
            critic_invoked = True
        repair_attempted = False
        if repairer is not None and any(issue.severity == "error" and issue.repairable
                                        for issue in issues):
            candidate = self.adapter.normalize(repairer(
                self.adapter.clone(candidate), deepcopy(issues)))
            repair_attempted = True
            issues = self.validator(candidate)
        return ConsistencyResult(
            plan=candidate.to_json(),  # type: ignore[attr-defined]
            issues=issues, risk=risk, critic_invoked=critic_invoked,
            repair_attempted=repair_attempted,
            repair_count=1 if repair_attempted else 0)


def validate_anima_semantics(plan: AnimaPromptPlan) -> list[SemanticIssue]:
    issues: list[SemanticIssue] = []
    seen: set[str] = set()
    for index, character in enumerate(plan.characters):
        base = f"characters/{index}"
        if not character.character_id.strip():
            issues.append(_issue("anima_character_id_missing", base + "/character_id",
                                 "人物缺少稳定 character_id", repairable=False))
        elif character.character_id in seen:
            issues.append(_issue("anima_character_id_duplicate", base + "/character_id",
                                 f"character_id {character.character_id!r} 重复"))
        seen.add(character.character_id)
        overlap = set(character.required_traits) & set(character.variable_traits)
        if overlap:
            issues.append(_issue(
                "anima_trait_ownership", base,
                "同一特征不能同时由稳定与可变字段拥有",
                evidence=sorted(overlap), repairable=True))
    positives = {item.lower() for character in plan.characters
                 for item in [*character.required_traits, *character.variable_traits]
                 if item.strip()}
    for index, constraint in enumerate(plan.negative_constraints):
        clean = constraint.lower().removeprefix("no ").strip()
        if clean in positives:
            issues.append(_issue(
                "anima_positive_negative_conflict", f"negative_constraints/{index}",
                f"正向事实与负向约束冲突: {clean}", evidence=[clean]))
    return issues


def validate_h3_semantics(plan: H3PromptPlan) -> list[SemanticIssue]:
    issues: list[SemanticIssue] = []
    if not 4.0 <= plan.duration_seconds <= 15.0:
        issues.append(_issue("h3_duration", "duration_seconds",
                             "MiniMax H3 时长必须为 4–15 秒"))
    previous = -1.0
    for position, shot in enumerate(plan.shots):
        base = f"shots/{position}"
        if shot.index != position + 1:
            issues.append(_issue("h3_shot_index", base + "/index",
                                 "镜头编号必须从 1 连续递增", repairable=True))
        if position == 0 and shot.start_time is not None:
            issues.append(_issue("h3_shot1_time", base + "/start_time",
                                 "Shot 1 不得有时间戳", repairable=True))
        if position > 0:
            if shot.start_time is None:
                issues.append(_issue("h3_shot_time_missing", base + "/start_time",
                                     "后续镜头必须有切点时间"))
            elif shot.start_time <= previous or shot.start_time >= plan.duration_seconds:
                issues.append(_issue("h3_shot_time_order", base + "/start_time",
                                     "切点必须严格递增且小于总时长"))
        if shot.start_time is not None:
            previous = shot.start_time
    speaker_ids = [speaker.speaker_id for speaker in plan.speakers]
    if len(speaker_ids) != len(set(speaker_ids)):
        issues.append(_issue("h3_speaker_duplicate", "speakers",
                             "说话人 ID 必须全片唯一且稳定"))
    defined_speakers = set(speaker_ids)
    defined_refs = {label.strip("<>") for label in plan.all_reference_labels()}
    used_refs: set[str] = set()
    for shot_index, shot in enumerate(plan.shots):
        used_refs.update(label.strip("<>") for label in shot.references)
        for dialogue_index, dialogue in enumerate(shot.dialogues):
            for speaker_id in dialogue.speaker_ids:
                if speaker_id not in defined_speakers:
                    issues.append(_issue(
                        "h3_speaker_undefined",
                        f"shots/{shot_index}/dialogues/{dialogue_index}/speaker_ids",
                        f"对白使用未定义说话人 {speaker_id}"))
            if dialogue.kind == "voiceover" and not dialogue.lips_closed:
                issues.append(_issue(
                    "h3_voiceover_lips",
                    f"shots/{shot_index}/dialogues/{dialogue_index}/lips_closed",
                    "画外音要求画面中人物嘴唇保持闭合", repairable=True))
    for label in sorted(used_refs - defined_refs):
        issues.append(_issue("h3_reference_undefined", "shots/*/references",
                             f"镜头使用未定义引用 <{label}>"))
    if plan.mode in {"Ref2VA", "R2V"}:
        retained = {item.label.strip("<>") for item in plan.retention}
        for label in sorted(defined_refs - used_refs):
            issues.append(_issue("h3_reference_unused", "shots/*/references",
                                 f"引用 <{label}> 未在具体镜头生效"))
        for label in sorted(defined_refs - retained):
            issues.append(_issue("h3_retention_missing", "retention",
                                 f"引用 <{label}> 缺少 retention 决策"))
    if not plan.explicit_silence and not plan.soundscape.strip():
        issues.append(_issue("h3_soundscape_empty", "soundscape",
                             "未明确全片静音时必须描述整体声景"))
    return issues


def deterministic_h3_repair(plan: H3PromptPlan,
                            issues: list[SemanticIssue]) -> H3PromptPlan:
    """Repair only mechanical H3 issues that have one unambiguous outcome."""
    codes = {issue.code for issue in issues if issue.repairable}
    if "h3_shot_index" in codes:
        for index, shot in enumerate(plan.shots, start=1):
            shot.index = index
    if "h3_shot1_time" in codes and plan.shots:
        plan.shots[0].start_time = None
    if "h3_voiceover_lips" in codes:
        for shot in plan.shots:
            for dialogue in shot.dialogues:
                if dialogue.kind == "voiceover":
                    dialogue.lips_closed = True
    return plan


def _issue(code: str, path: str, message: str, *,
           evidence: list[str] | None = None,
           repairable: bool = False) -> SemanticIssue:
    return SemanticIssue(severity="error", code=code, path=path, message=message,
                         reason="确定性语义不变量未满足",
                         evidence=evidence or [], repairable=repairable)


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))

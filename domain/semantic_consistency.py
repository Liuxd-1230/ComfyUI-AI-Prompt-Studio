"""Deterministic semantics, risk-triggered criticism, and bounded repair."""
from __future__ import annotations

from typing import Any, Callable, Generic, Protocol, TypeVar

from ..schemas.anima import AnimaPromptPlan
from ..schemas.changeset import ChangeSet, SemanticChange
from ..schemas.h3 import H3PromptPlan
from ..schemas.semantic import ConsistencyResult, RiskAssessment, SemanticIssue
from .plan_adapters import PlanAdapter
from .impact_analysis import analyze_anima_impacts


PlanT = TypeVar("PlanT")


class SemanticCritic(Protocol[PlanT]):
    def __call__(self, plan: PlanT, changeset: ChangeSet) -> list[SemanticIssue]: ...


Validator = Callable[[PlanT], list[SemanticIssue]]


HIGH_RISK_FIELDS = {
    "action", "actions", "character_id", "identity", "location", "environment",
    "references", "retention", "dialogues", "speaker", "speaker_ids", "duration",
    "duration_seconds", "start_time", "camera", "camera_motion", "camera_target",
    "scene_description", "required_traits", "name", "position", "definition",
    "source_assets", "label", "source",
}
STRUCTURAL_COLLECTIONS = {
    "shots", "characters", "subjects", "assets", "speakers", "clauses",
}
LOW_RISK_FIELDS = {
    "lighting", "color", "colour", "material", "variable_traits",
    "clothing", "wardrobe",
}
SIMPLE_STYLE_PRESETS = {
    "anime", "watercolor", "oil painting", "ink wash", "cel shading",
    "photorealistic", "cinematic", "pixel art", "line art",
}


def assess_risk(changeset: ChangeSet) -> RiskAssessment:
    score = 0
    reasons: list[str] = []
    if changeset.change_category == "broad_rewrite":
        score = 4
        reasons.append("用户授权大范围重构")
    for change in changeset.all_changes():
        parts = [part.lower() for part in change.path.split("/") if part]
        leaf = parts[-1] if parts else ""
        collection_root = (parts[1] if len(parts) > 1 and parts[0] == "content"
                           else parts[0] if parts else "")
        structural = bool(collection_root in STRUCTURAL_COLLECTIONS
                          and change.operation in {"insert", "delete"})
        high_field = any(part in HIGH_RISK_FIELDS for part in parts)
        # Editing an individual shot description can change action/object continuity
        # even when the wire schema calls it generic prose.
        shot_prose = bool(parts and parts[0] == "shots"
                          and leaf in {"description", "audio_notes", "on_screen_text"})
        negative_path = "negative" in parts or "negative_constraints" in parts
        negative_size = (len(change.value) if isinstance(change.value, list)
                         else len([part for part in str(change.value).split(",")
                                  if part.strip()]))
        broad_negative = negative_path and (
            change.operation == "delete" or negative_size >= 3)
        major_composition = "composition" in parts and (
            change.operation in {"insert", "delete"}
            or len(str(change.value or "")) >= 120)
        style_path = "style" in parts
        simple_style = (style_path and change.operation == "set"
                        and str(change.value or "").strip().casefold()
                        in SIMPLE_STYLE_PRESETS)
        low_leaf = (leaf in LOW_RISK_FIELDS or "variable_traits" in parts
                    or simple_style)
        if (structural or high_field or shot_prose or broad_negative
                or major_composition or (style_path and not simple_style)):
            score += 3
            reasons.append(f"高影响语义路径: {change.path}")
        elif not low_leaf and any(part in {"shots", "characters", "subjects", "assets"}
                                  for part in parts):
            score += 1
            reasons.append(f"关联语义路径: {change.path}")
    if any(not change.reason.startswith("deterministic:")
           for change in changeset.dependent_changes):
        score += 1
        reasons.append("包含依赖闭包变更")
    if any(not fact.reason.startswith("deterministic:")
           for fact in changeset.invalidated_facts):
        score += 2
        reasons.append("存在失效事实")
    if changeset.constraint_conflicts:
        score += 4
        reasons.append("存在约束冲突")
    level = "high" if score >= 3 else "medium" if score else "low"
    return RiskAssessment(level=level, score=score, reasons=_dedupe(reasons),
                          critic_required=level == "high")


class SemanticConsistencyPipeline(Generic[PlanT]):
    """Evaluate a candidate without mutation; repair belongs to guarded transactions."""

    def __init__(self, adapter: PlanAdapter[PlanT], validator: Validator[PlanT]) -> None:
        self.adapter = adapter
        self.validator = validator

    def run(self, plan: PlanT, changeset: ChangeSet, *,
            critic: SemanticCritic[PlanT] | None = None,
            force_critic: bool = False,
            repair_count: int = 0) -> ConsistencyResult:
        candidate = self.adapter.normalize(self.adapter.clone(plan))
        risk = assess_risk(changeset)
        issues = self.validator(candidate)
        critic_invoked = False
        critic_required = risk.critic_required or force_critic
        if force_critic and not risk.critic_required:
            risk.level, risk.score, risk.critic_required = "high", max(3, risk.score), True
            risk.reasons.append("修复前候选属于高风险，必须再次 Critic")
        if critic_required and critic is None:
            raise ValueError("高风险语义变更必须提供 Semantic Critic，不能静默跳过")
        if critic_required and critic is not None:
            issues.extend(critic(candidate, changeset))
            critic_invoked = True
        return ConsistencyResult(
            plan=candidate.to_json(),  # type: ignore[attr-defined]
            issues=issues, risk=risk, critic_invoked=critic_invoked,
            repair_attempted=repair_count > 0,
            repair_count=max(0, int(repair_count)))


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
    styles = {value.strip().casefold() for value in plan.style if value.strip()}
    realistic = {"photorealistic", "realistic", "photo"}
    illustrative = {"anime", "cel shading", "illustration", "line art"}
    if styles & realistic and styles & illustrative:
        issues.append(_issue(
            "anima_style_conflict", "style",
            "风格同时要求写实摄影与插画/动漫表现，且未声明混合方式",
            evidence=sorted(styles & (realistic | illustrative)), repairable=True))
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
    reference_shots: dict[str, set[int]] = {}
    for shot_index, shot in enumerate(plan.shots):
        for character_id in shot.characters:
            if character_id not in defined_speakers:
                issues.append(_issue(
                    "h3_visible_character_undefined",
                    f"shots/{shot_index}/characters",
                    f"镜头使用未定义人物/说话人 {character_id}"))
        for label in shot.references:
            clean_label = label.strip("<>")
            used_refs.add(clean_label)
            reference_shots.setdefault(clean_label, set()).add(shot_index)
        for dialogue_index, dialogue in enumerate(shot.dialogues):
            for speaker_id in dialogue.speaker_ids:
                if speaker_id not in defined_speakers:
                    issues.append(_issue(
                        "h3_speaker_undefined",
                        f"shots/{shot_index}/dialogues/{dialogue_index}/speaker_ids",
                        f"对白使用未定义说话人 {speaker_id}"))
                elif dialogue.kind != "voiceover" and speaker_id not in shot.characters:
                    issues.append(_issue(
                        "h3_speaker_not_visible",
                        f"shots/{shot_index}/dialogues/{dialogue_index}/speaker_ids",
                        f"可见对白说话人 {speaker_id} 未列入本镜头 characters"))
            if dialogue.kind == "voiceover" and not dialogue.lips_closed:
                issues.append(_issue(
                    "h3_voiceover_lips",
                    f"shots/{shot_index}/dialogues/{dialogue_index}/lips_closed",
                    "画外音要求画面中人物嘴唇保持闭合", repairable=True))
    for label in sorted(used_refs - defined_refs):
        for shot_index in sorted(reference_shots.get(label, set())):
            issues.append(_issue(
                "h3_reference_undefined", f"shots/{shot_index}/references",
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
    issues.extend(_adjacent_h3_continuity_issues(plan))
    return issues


def _adjacent_h3_continuity_issues(plan: H3PromptPlan) -> list[SemanticIssue]:
    """Catch explicit drop→hold gaps; ambiguous creative prose remains Critic territory."""
    import re

    issues: list[SemanticIssue] = []
    intentional = re.compile(
        r"\b(?:picks?\s+up|retrieves?|recovers?|dream|flashback|montage|"
        r"smash\s+cut|time\s+jump)\b|捡起|拾起|重新拿起|梦境|闪回|蒙太奇|时间跳跃|转场",
        re.IGNORECASE)
    dropped_patterns = [
        re.compile(r"\b(?:drops?|releases?|discards?)\s+"
                   r"(?:(?:the|a|an|his|her|their)\s+)?([\w-]+)", re.I),
        re.compile(r"(?:放下|丢下|扔下)([\u3400-\u9fff]{1,8})"),
    ]
    held_patterns = [
        re.compile(r"\b(?:holds?|carries?|grips?)\s+"
                   r"(?:(?:the|a|an|his|her|their)\s+)?([\w-]+)", re.I),
        re.compile(r"(?:拿着|握着|举着)([\u3400-\u9fff]{1,8})"),
    ]
    for index in range(1, len(plan.shots)):
        previous = " ".join(plan.shots[index - 1].description)
        current = " ".join(plan.shots[index].description)
        dropped = {match.group(1).casefold() for pattern in dropped_patterns
                   for match in pattern.finditer(previous)}
        held = {match.group(1).casefold() for pattern in held_patterns
                for match in pattern.finditer(current)}
        gap = sorted(dropped & held)
        if gap and not intentional.search(current):
            issues.append(_issue(
                "h3_object_state_gap", f"shots/{index}/description",
                f"相邻镜头物体状态缺少过渡：{', '.join(gap)} 从放下/丢弃直接变为持有",
                evidence=[f"Shot {index}", f"Shot {index + 1}"], repairable=True))
    return issues


def _issue(code: str, path: str, message: str, *,
           evidence: list[str] | None = None,
           repairable: bool = False) -> SemanticIssue:
    return SemanticIssue(severity="error", code=code, path=path, message=message,
                         reason="确定性语义不变量未满足",
                         evidence=evidence or [], repairable=repairable)


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def assert_repair_scope(changeset: ChangeSet,
                        allowed_paths: list[str]) -> None:
    """Reject model-proposed repair edits unrelated to concrete issue paths."""
    normalized = [_repair_root(path) for path in allowed_paths if path.strip()]
    unrelated = [change.path for change in changeset.all_changes()
                 if not any(_paths_overlap(change.path, allowed)
                            for allowed in normalized)]
    if unrelated:
        raise ValueError("Repair ChangeSet 包含与具体 issue 无关的路径：" +
                         ", ".join(unrelated))


def revalidation_changeset(original: ChangeSet, repair: ChangeSet) -> ChangeSet:
    """Describe stable→repaired effects so the post-repair Critic sees both deltas."""
    requested: dict[str, SemanticChange] = {
        change.path: change for change in original.requested_changes}
    requested.update({change.path: change for change in repair.requested_changes})
    dependent: dict[str, SemanticChange] = {
        change.path: change for change in original.dependent_changes}
    dependent.update({change.path: change for change in repair.dependent_changes})
    for path in set(requested) & set(dependent):
        dependent.pop(path, None)
    return ChangeSet(
        base_revision=original.base_revision,
        plan_type=original.plan_type,
        change_category=("broad_rewrite"
                         if original.change_category == "broad_rewrite"
                         else "repair"),
        intent_scope=list(dict.fromkeys(
            [*original.intent_scope, *repair.intent_scope])),
        requested_changes=list(requested.values()),
        dependent_changes=list(dependent.values()),
        invalidated_facts=[*original.invalidated_facts, *repair.invalidated_facts],
        constraint_conflicts=[*original.constraint_conflicts, *repair.constraint_conflicts],
        approved_requested_paths=list(requested),
        approved_dependent_paths=list(dependent),
        summary=f"{original.summary}; repair: {repair.summary}")


def _repair_root(path: str) -> str:
    parts = [part for part in path.strip().strip("/").split("/") if part]
    if "*" in parts:
        return ""
    return "/".join(parts)


def _paths_overlap(left: str, right: str) -> bool:
    return (left == right or left.startswith(right + "/")
            or right.startswith(left + "/"))

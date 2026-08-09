"""Deterministic dependency and invalidation closure for P2 transactions."""
from __future__ import annotations

import re
from typing import Protocol, TypeVar

from ..schemas.anima import AnimaPromptPlan
from ..schemas.changeset import ChangeSet, InvalidatedFact
from ..schemas.h3 import H3PromptPlan
from ..schemas.image_semantic_plan import ImageSemanticPlan


PlanT = TypeVar("PlanT")


class ImpactAnalyzer(Protocol[PlanT]):
    def __call__(self, plan: PlanT, changeset: ChangeSet) -> ChangeSet: ...


def analyze_anima_impacts(plan: AnimaPromptPlan, changeset: ChangeSet) -> ChangeSet:
    """Close deterministic ANIMA dependencies without guessing creative intent."""
    changed = {item.path for item in changeset.all_changes()}
    for change in changeset.all_changes():
        if change.path == "environment" and plan.lighting and "lighting" not in changed:
            _add_invalidation(
                changeset, "lighting",
                "环境变化可能使原光线来源或时间条件失效；必须同步更新或明确保留")
    return changeset


def analyze_h3_impacts(plan: H3PromptPlan, changeset: ChangeSet) -> ChangeSet:
    """Close H3 timeline invalidations that Python can prove."""
    duration_change = next((item for item in changeset.all_changes()
                            if item.path == "duration_seconds" and item.operation == "set"), None)
    if duration_change is not None and isinstance(duration_change.value, (int, float)):
        new_duration = float(duration_change.value)
        changed = {item.path for item in changeset.all_changes()}
        for index, shot in enumerate(plan.shots):
            path = f"shots/{index}/start_time"
            if shot.start_time is not None and shot.start_time >= new_duration and path not in changed:
                _add_invalidation(
                    changeset, path,
                    f"镜头切点 {shot.start_time:.3f}s 不小于新总时长 {new_duration:.3f}s")
    return changeset


def analyze_image_impacts(plan: ImageSemanticPlan, changeset: ChangeSet) -> ChangeSet:
    """Keep positive content and negative constraints in one dependency graph."""
    changed = {item.path for item in changeset.all_changes()}
    content = plan.content
    if (any(item.path == "content/environment" for item in changeset.all_changes())
            and str(content.get("lighting", "")).strip()
            and "content/lighting" not in changed):
        _add_invalidation(
            changeset, "content/lighting",
            "环境变化可能使原光线来源或时间条件失效；必须同步更新或明确保留")
    negative_tokens = _negative_tokens(plan.negative)
    if "negative" not in changed:
        for change in changeset.all_changes():
            if not change.path.startswith("content/"):
                continue
            values = _string_leaves(change.value)
            conflict = next((value for value in values
                             if _first_conflict(value, negative_tokens)), "")
            if conflict:
                _add_invalidation(
                    changeset, "negative",
                    f"新增正向事实 {conflict!r} 与现有负向约束冲突")
                break
    return changeset


def validate_image_candidate(plan: ImageSemanticPlan) -> list[str]:
    """Reject positive/negative contradictions in the actual post-change candidate."""
    positive = " ".join(_string_leaves(plan.content))
    conflicts = sorted({token for token in _negative_tokens(plan.negative)
                        if _contains_semantic_token(positive, token)})
    return [f"正向内容与负向约束仍冲突: {token}" for token in conflicts]


def passthrough_impacts(plan: PlanT, changeset: ChangeSet) -> ChangeSet:
    """Typed no-op for plans without deterministic cross-field dependencies."""
    del plan
    return changeset


def _add_invalidation(changeset: ChangeSet, path: str, reason: str) -> None:
    if not any(item.path == path for item in changeset.invalidated_facts):
        changeset.invalidated_facts.append(InvalidatedFact(path=path, reason=reason))


def _string_leaves(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [leaf for item in value for leaf in _string_leaves(item)]
    if isinstance(value, dict):
        return [leaf for item in value.values() for leaf in _string_leaves(item)]
    return []


def _negative_tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for item in str(value or "").split(","):
        clean = item.strip().casefold()
        clean = re.sub(r"^(?:no|without)\s+", "", clean)
        if len(clean) >= 2:
            tokens.add(clean)
    return tokens


def _first_conflict(value: str, tokens: set[str]) -> str:
    return next((token for token in tokens if _contains_semantic_token(value, token)), "")


def _contains_semantic_token(text: str, token: str) -> bool:
    haystack = str(text or "").casefold()
    if not token:
        return False
    if re.search(r"[\u3400-\u9fff]", token):
        return token in haystack
    pattern = r"(?<![\w])" + re.escape(token).replace(r"\ ", r"[\s_-]+") + r"(?![\w])"
    return re.search(pattern, haystack) is not None

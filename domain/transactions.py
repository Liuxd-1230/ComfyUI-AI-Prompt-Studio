"""Clone-first semantic transaction and authorization Diff Guard."""
from __future__ import annotations

import dataclasses
from copy import deepcopy
from typing import Any, Callable, Generic, TypeVar

from ..schemas.changeset import ChangeSet, SemanticChange
from ..schemas.semantic_paths import path_within, paths_overlap
from .plan_adapters import PlanAdapter


PlanT = TypeVar("PlanT")


class TransactionRejected(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class TransactionResult(Generic[PlanT]):
    plan: PlanT
    changed_paths: tuple[str, ...]
    changeset: ChangeSet


class SemanticTransaction(Generic[PlanT]):
    """Apply a ChangeSet to a clone and commit only after every gate passes."""

    def __init__(self, adapter: PlanAdapter[PlanT]) -> None:
        self.adapter = adapter

    def execute(self, current: PlanT, changeset: ChangeSet, *,
                current_revision: int,
                impact_analyzer: Callable[[PlanT, ChangeSet], ChangeSet] | None = None,
                semantic_check: Callable[[PlanT], list[Any]] | None = None,
                allowed_roots: list[str] | tuple[str, ...] = (),
                locked_paths: list[str] | tuple[str, ...] = (),
                broad_only_roots: list[str] | tuple[str, ...] = (),
                normalization_paths: list[str] | tuple[str, ...] = (),
                normalizer: Callable[[PlanT], PlanT] | None = None,
                allow_broad: bool = False) -> TransactionResult[PlanT]:
        proposed = deepcopy(changeset)
        self._validate_contract(proposed, current_revision)
        proposed_dependent = {change.path for change in proposed.dependent_changes}
        analysis_plan = self.adapter.clone(current)
        effective = (impact_analyzer(analysis_plan, proposed)
                     if impact_analyzer is not None else proposed)
        self._validate_contract(effective, current_revision)
        if effective.change_category == "broad_rewrite" and not allow_broad:
            raise TransactionRejected(
                "broad_rewrite 未获得用户明确的大范围重建授权")
        unapproved_requested = [
            change.path for change in effective.requested_changes
            if not path_within(change.path, effective.approved_requested_paths)]
        if unapproved_requested:
            raise TransactionRejected(
                "Intent Grounding 未授权请求变更：" +
                ", ".join(unapproved_requested))
        deterministic_dependencies = {
            change.path for change in effective.dependent_changes
            if change.path not in proposed_dependent}
        approved_dependencies = tuple(
            [*effective.approved_dependent_paths, *deterministic_dependencies])
        unapproved_dependencies = [
            change.path for change in effective.dependent_changes
            if not path_within(change.path, approved_dependencies)]
        if unapproved_dependencies:
            raise TransactionRejected(
                "Impact Analysis 未批准依赖变更：" +
                ", ".join(unapproved_dependencies))
        if effective.constraint_conflicts:
            details = "；".join(conflict.reason for conflict in effective.constraint_conflicts)
            raise TransactionRejected("存在未解决约束冲突：" + details)
        changed_roots = tuple(change.path for change in effective.all_changes())
        unresolved = [fact for fact in effective.invalidated_facts
                      if not _authorized(fact.path, changed_roots)]
        if unresolved:
            raise TransactionRejected(
                "存在未解决失效事实：" + "；".join(
                    f"{fact.path} ({fact.reason})" for fact in unresolved))

        before = self.adapter.clone(current)
        payload = self.adapter.dump(before)
        for change in effective.all_changes():
            if (effective.change_category != "broad_rewrite"
                    and change.path in broad_only_roots):
                raise TransactionRejected(
                    f"change category {effective.change_category} 不允许替换结构根: {change.path}")
            _authorize_change(change, payload, tuple(allowed_roots), tuple(locked_paths))
            _apply(payload, change)
        applied = self.adapter.load(payload)
        proposal_changed = tuple(sorted(_diff_paths(
            self.adapter.dump(before), self.adapter.dump(applied))))
        proposal_authorized = tuple(_authorization_root(change)
                                    for change in effective.all_changes()) + tuple(
                                        fact.path for fact in effective.invalidated_facts)
        unauthorized = [path for path in proposal_changed
                        if not _authorized(path, proposal_authorized)]
        if unauthorized:
            raise TransactionRejected(
                "Diff Guard 拒绝未授权变更：" + ", ".join(unauthorized))
        candidate = self.adapter.normalize(applied)
        if normalizer is not None:
            candidate = normalizer(self.adapter.clone(candidate))
        normalization_changed = tuple(sorted(_diff_paths(
            self.adapter.dump(applied), self.adapter.dump(candidate))))
        locked_normalization = [path for path in normalization_changed
                                if any(paths_overlap(path, locked)
                                       for locked in locked_paths)]
        if locked_normalization:
            raise TransactionRejected(
                "locked path 拒绝确定性归一化变更：" +
                ", ".join(locked_normalization))
        unauthorized_normalization = [path for path in normalization_changed
                                      if not _authorized(path, tuple(normalization_paths))]
        if unauthorized_normalization:
            raise TransactionRejected(
                "Diff Guard 拒绝未授权的确定性归一化：" +
                ", ".join(unauthorized_normalization))
        changed = tuple(sorted(_diff_paths(
            self.adapter.dump(before), self.adapter.dump(candidate))))
        semantic_issues = semantic_check(candidate) if semantic_check else []
        if semantic_issues:
            raise TransactionRejected("语义校验失败：" + "；".join(
                str(getattr(issue, "message", issue)) for issue in semantic_issues))
        return TransactionResult(candidate, changed, effective)

    def _validate_contract(self, changeset: ChangeSet,
                           current_revision: int) -> None:
        issues = changeset.validate()
        if issues:
            raise TransactionRejected("ChangeSet 校验失败：" + "；".join(issues))
        if changeset.base_revision != current_revision:
            raise TransactionRejected(
                f"revision 冲突：请求基于 {changeset.base_revision}，当前为 {current_revision}")
        if changeset.plan_type != self.adapter.family:
            raise TransactionRejected(
                f"plan_type 不匹配：请求为 {changeset.plan_type!r}，"
                f"当前计划为 {self.adapter.family!r}")


def _parts(path: str) -> list[str]:
    return [part for part in path.split("/") if part]


_IMMUTABLE_ROOTS = {"schema_version", "normal_form_version", "plan_type"}


def _authorize_change(change: SemanticChange, payload: dict[str, Any],
                      allowed_roots: tuple[str, ...],
                      locked_paths: tuple[str, ...]) -> None:
    parts = _parts(change.path)
    if (not parts or any(part in _IMMUTABLE_ROOTS for part in parts)
            or any(part.startswith("__") for part in parts)):
        raise TransactionRejected(f"禁止修改不可变或魔术路径: {change.path}")
    if allowed_roots and not path_within(change.path, allowed_roots):
        raise TransactionRejected(f"allowed root 拒绝变更: {change.path}")
    if any(paths_overlap(change.path, locked) for locked in locked_paths):
        raise TransactionRejected(f"locked path 拒绝变更: {change.path}")
    if change.operation == "insert":
        if "/" not in change.path:
            raise TransactionRejected(f"insert 路径必须包含列表索引: {change.path}")
        parent_path, leaf = change.path.rsplit("/", 1)
        parent = _read(payload, parent_path)
        if not isinstance(parent, list) or not leaf.isdigit() or int(leaf) > len(parent):
            raise TransactionRejected(f"insert 列表索引无效: {change.path}")
        if parent and not _compatible_value(parent[0], change.value):
            raise TransactionRejected(f"value type 不匹配: {change.path}")
        return
    current = _read(payload, change.path)
    if change.operation == "set" and not _compatible_value(current, change.value):
        raise TransactionRejected(
            f"value type 不匹配: {change.path} 期望 {type(current).__name__}，"
            f"实际 {type(change.value).__name__}")


def _read(root: Any, path: str) -> Any:
    current = root
    try:
        for part in _parts(path):
            current = current[int(part)] if isinstance(current, list) else current[part]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise TransactionRejected(f"无法应用变更，路径不存在: {path}") from exc
    return current


def _compatible_value(current: Any, proposed: Any) -> bool:
    if current is None:
        return True
    if isinstance(current, bool):
        return isinstance(proposed, bool)
    return type(current) is type(proposed)


def _apply(root: dict[str, Any], change: SemanticChange) -> None:
    parts = _parts(change.path)
    if not parts:
        raise TransactionRejected("禁止替换整个计划根对象")
    parent: Any = root
    for part in parts[:-1]:
        try:
            parent = parent[int(part)] if isinstance(parent, list) else parent[part]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise TransactionRejected(f"变更路径不存在: {change.path}") from exc
    leaf = parts[-1]
    try:
        if change.operation == "set":
            if isinstance(parent, list):
                parent[int(leaf)] = change.value
            else:
                if leaf not in parent:
                    raise KeyError(leaf)
                parent[leaf] = change.value
        elif change.operation == "delete":
            if isinstance(parent, list):
                del parent[int(leaf)]
            else:
                del parent[leaf]
        elif change.operation == "insert":
            if not isinstance(parent, list):
                raise TypeError("insert 只能用于列表")
            parent.insert(int(leaf), change.value)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise TransactionRejected(f"无法应用变更 {change.path}: {exc}") from exc


def _diff_paths(before: Any, after: Any, prefix: str = "") -> set[str]:
    if type(before) is not type(after):
        return {prefix}
    if isinstance(before, dict):
        changed: set[str] = set()
        for key in before.keys() | after.keys():
            path = f"{prefix}/{key}" if prefix else str(key)
            if key not in before or key not in after:
                changed.add(path)
            else:
                changed.update(_diff_paths(before[key], after[key], path))
        return changed
    if isinstance(before, list):
        changed = set()
        for index in range(max(len(before), len(after))):
            path = f"{prefix}/{index}" if prefix else str(index)
            if index >= len(before) or index >= len(after):
                changed.add(path)
            else:
                changed.update(_diff_paths(before[index], after[index], path))
        return changed
    return {prefix} if before != after else set()


def _authorized(path: str, authorized: tuple[str, ...]) -> bool:
    return any(path == root or path.startswith(root + "/") or root.startswith(path + "/")
               for root in authorized)


def _authorization_root(change: SemanticChange) -> str:
    """List insert/delete authorizes deterministic index shifts in that list."""
    if change.operation in {"insert", "delete"} and "/" in change.path:
        return change.path.rsplit("/", 1)[0]
    return change.path

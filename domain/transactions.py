"""Clone-first semantic transaction and authorization Diff Guard."""
from __future__ import annotations

import dataclasses
from typing import Any, Callable, Generic, TypeVar

from ..schemas.changeset import ChangeSet, SemanticChange
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
                semantic_check: Callable[[PlanT], list[str]] | None = None,
                commit: Callable[[PlanT], None] | None = None) -> TransactionResult[PlanT]:
        issues = changeset.validate()
        if issues:
            raise TransactionRejected("ChangeSet 校验失败：" + "；".join(issues))
        if changeset.base_revision != current_revision:
            raise TransactionRejected(
                f"revision 冲突：请求基于 {changeset.base_revision}，当前为 {current_revision}")
        if changeset.constraint_conflicts:
            details = "；".join(conflict.reason for conflict in changeset.constraint_conflicts)
            raise TransactionRejected("存在未解决约束冲突：" + details)

        before = self.adapter.normalize(self.adapter.clone(current))
        payload = before.to_json()  # type: ignore[attr-defined]
        for change in changeset.all_changes():
            _apply(payload, change)
        candidate = self.adapter.normalize(self.adapter.load(payload))

        changed = tuple(sorted(_diff_paths(before.to_json(), candidate.to_json())))  # type: ignore[attr-defined]
        authorized = tuple(_authorization_root(change)
                           for change in changeset.all_changes())
        unauthorized = [path for path in changed if not _authorized(path, authorized)]
        if unauthorized:
            raise TransactionRejected(
                "Diff Guard 拒绝未授权变更：" + ", ".join(unauthorized))
        semantic_issues = semantic_check(candidate) if semantic_check else []
        if semantic_issues:
            raise TransactionRejected("语义校验失败：" + "；".join(semantic_issues))
        if commit is not None:
            commit(candidate)
        return TransactionResult(candidate, changed, changeset)


def _parts(path: str) -> list[str]:
    return [part for part in path.split("/") if part]


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

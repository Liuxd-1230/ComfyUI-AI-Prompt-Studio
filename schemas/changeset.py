"""Reasoned semantic mutations used by Prompt Studio transactions."""
import dataclasses
from typing import Any

from .base import Schema


CHANGE_OPERATIONS = {"set", "delete", "insert"}
CHANGE_CATEGORIES = {"minimal_refine", "broad_rewrite", "migration", "repair"}


def _valid_path(path: str) -> bool:
    parts = path.split("/")
    return bool(path and not path.startswith("/") and all(
        part and part not in {".", ".."} and not part.startswith("__")
        for part in parts))


@dataclasses.dataclass
class SemanticChange(Schema):
    path: str = ""
    operation: str = "set"
    value: Any = None
    reason: str = ""

    def validate(self) -> list[str]:
        issues: list[str] = []
        if not _valid_path(self.path):
            issues.append(f"非法语义路径: {self.path!r}")
        if self.operation not in CHANGE_OPERATIONS:
            issues.append(f"不支持的变更操作: {self.operation!r}")
        if not self.reason.strip():
            issues.append(f"变更 {self.path or '<empty>'} 缺少 reason")
        return issues


@dataclasses.dataclass
class InvalidatedFact(Schema):
    path: str = ""
    reason: str = ""


@dataclasses.dataclass
class ConstraintConflict(Schema):
    path: str = ""
    constraint: str = ""
    reason: str = ""


@dataclasses.dataclass
class ChangeSet(Schema):
    base_revision: int = 0
    plan_type: str = ""
    change_category: str = "minimal_refine"
    intent_scope: list[str] = dataclasses.field(default_factory=list)
    requested_changes: list[SemanticChange] = dataclasses.field(default_factory=list)
    dependent_changes: list[SemanticChange] = dataclasses.field(default_factory=list)
    invalidated_facts: list[InvalidatedFact] = dataclasses.field(default_factory=list)
    constraint_conflicts: list[ConstraintConflict] = dataclasses.field(default_factory=list)
    approved_requested_paths: list[str] = dataclasses.field(default_factory=list)
    approved_dependent_paths: list[str] = dataclasses.field(default_factory=list)
    summary: str = ""

    def all_changes(self) -> list[SemanticChange]:
        return [*self.requested_changes, *self.dependent_changes]

    def validate(self) -> list[str]:
        issues: list[str] = []
        if self.base_revision < 0:
            issues.append("base_revision 不能为负数")
        if not self.plan_type.strip():
            issues.append("plan_type 不能为空")
        if self.change_category not in CHANGE_CATEGORIES:
            issues.append(f"不支持的 change_category: {self.change_category!r}")
        if not self.intent_scope:
            issues.append("intent_scope 不能为空")
        if not self.requested_changes:
            issues.append("requested_changes 不能为空")
        if not self.summary.strip():
            issues.append("summary 不能为空")
        for change in self.all_changes():
            issues.extend(change.validate())
        seen_paths: set[str] = set()
        for change in self.all_changes():
            if change.path in seen_paths:
                issues.append(f"同一路径不能声明多个变更: {change.path}")
            seen_paths.add(change.path)
        for change in self.requested_changes:
            if not any(_paths_overlap(change.path, scope)
                       for scope in self.intent_scope):
                issues.append(
                    f"请求变更 {change.path} 不在 intent_scope 授权范围内")
        for fact in self.invalidated_facts:
            if not _valid_path(fact.path) or not fact.reason.strip():
                issues.append("invalidated_facts 的 path/reason 不能为空")
        for conflict in self.constraint_conflicts:
            if (not _valid_path(conflict.path) or not conflict.constraint
                    or not conflict.reason.strip()):
                issues.append("constraint_conflicts 的 path/constraint/reason 不能为空")
        return issues


def _paths_overlap(left: str, right: str) -> bool:
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")

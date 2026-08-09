from __future__ import annotations

import pytest

from aps.domain.plan_adapters import AnimaPlanAdapter
from aps.domain.transactions import SemanticTransaction, TransactionRejected
from aps.schemas.anima import AnimaCharacter, AnimaPromptPlan
from aps.schemas.changeset import (ChangeSet, ConstraintConflict,
                                   SemanticChange)


def _plan() -> AnimaPromptPlan:
    return AnimaPromptPlan(
        scene_description="A rainy street.",
        characters=[AnimaCharacter(character_id="c1", variable_traits=["red coat"],
                                   action="walking")],
        lighting="blue hour")


def _change(path: str, value, reason: str = "用户明确要求") -> SemanticChange:
    return SemanticChange(path=path, value=value, reason=reason)


def test_transaction_applies_to_clone_and_commits_atomically() -> None:
    original = _plan()
    committed: list[AnimaPromptPlan] = []
    changeset = ChangeSet(
        base_revision=3, intent_scope=["character.clothing"],
        requested_changes=[_change("characters/0/variable_traits", ["black coat"])],
        summary="把外套改成黑色")
    result = SemanticTransaction(AnimaPlanAdapter()).execute(
        original, changeset, current_revision=3, commit=committed.append)
    assert original.characters[0].variable_traits == ["red coat"]
    assert result.plan.characters[0].variable_traits == ["black coat"]
    assert result.changed_paths == ("characters/0/variable_traits/0",)
    assert committed == [result.plan]


def test_malformed_or_stale_changeset_never_commits() -> None:
    committed = []
    malformed = ChangeSet(base_revision=1, intent_scope=[], requested_changes=[], summary="")
    with pytest.raises(TransactionRejected, match="ChangeSet"):
        SemanticTransaction(AnimaPlanAdapter()).execute(
            _plan(), malformed, current_revision=1, commit=committed.append)
    stale = ChangeSet(base_revision=0, intent_scope=["lighting"],
                      requested_changes=[_change("lighting", "noon")], summary="改光线")
    with pytest.raises(TransactionRejected, match="revision"):
        SemanticTransaction(AnimaPlanAdapter()).execute(
            _plan(), stale, current_revision=1, commit=committed.append)
    assert committed == []


def test_unresolved_conflict_and_semantic_failure_never_commit() -> None:
    committed = []
    changeset = ChangeSet(
        base_revision=1, intent_scope=["lighting"],
        requested_changes=[_change("lighting", "noon")], summary="改光线",
        constraint_conflicts=[ConstraintConflict(
            path="lighting", constraint="locked", reason="光线被镜头连续性锁定")])
    with pytest.raises(TransactionRejected, match="约束冲突"):
        SemanticTransaction(AnimaPlanAdapter()).execute(
            _plan(), changeset, current_revision=1, commit=committed.append)
    changeset.constraint_conflicts = []
    with pytest.raises(TransactionRejected, match="语义校验"):
        SemanticTransaction(AnimaPlanAdapter()).execute(
            _plan(), changeset, current_revision=1,
            semantic_check=lambda _: ["forced failure"], commit=committed.append)
    assert committed == []


def test_missing_path_is_rejected_instead_of_creating_arbitrary_state() -> None:
    changeset = ChangeSet(
        base_revision=1, intent_scope=["unknown"],
        requested_changes=[_change("characters/0/secret", "x")], summary="非法")
    with pytest.raises(TransactionRejected, match="无法应用变更"):
        SemanticTransaction(AnimaPlanAdapter()).execute(
            _plan(), changeset, current_revision=1)


def test_list_delete_authorizes_only_structural_index_shift() -> None:
    plan = _plan()
    plan.characters.append(AnimaCharacter(character_id="c2", action="running"))
    changeset = ChangeSet(
        base_revision=1, intent_scope=["character.remove"],
        requested_changes=[SemanticChange(
            path="characters/0", operation="delete", reason="用户删除第一个角色")],
        summary="删除第一个角色")
    result = SemanticTransaction(AnimaPlanAdapter()).execute(
        plan, changeset, current_revision=1)
    assert [character.character_id for character in result.plan.characters] == ["c2"]
    assert all(path.startswith("characters/") for path in result.changed_paths)

from __future__ import annotations

import pytest

from aps.domain.plan_adapters import (AnimaPlanAdapter, H3PlanAdapter,
                                      get_session_plan_adapter)
from aps.domain.impact_analysis import (analyze_h3_impacts, analyze_image_impacts,
                                        validate_image_candidate)
from aps.domain.transactions import SemanticTransaction, TransactionRejected
from aps.schemas.anima import AnimaCharacter, AnimaPromptPlan
from aps.schemas.image_semantic_plan import ImageSemanticPlan
from aps.schemas.h3 import H3PromptPlan, H3Shot
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
    changeset = ChangeSet(
        base_revision=3, plan_type="anima", change_category="minimal_refine",
        intent_scope=["characters/0/variable_traits"],
        approved_requested_paths=["characters/0/variable_traits"],
        requested_changes=[_change("characters/0/variable_traits", ["black coat"])],
        summary="把外套改成黑色")
    result = SemanticTransaction(AnimaPlanAdapter()).execute(
        original, changeset, current_revision=3,
        allowed_roots=["characters"], locked_paths=[])
    assert original.characters[0].variable_traits == ["red coat"]
    assert result.plan.characters[0].variable_traits == ["black coat"]
    assert result.changed_paths == ("characters/0/variable_traits/0",)


def test_malformed_or_stale_changeset_never_commits() -> None:
    malformed = ChangeSet(base_revision=1, plan_type="anima", intent_scope=[],
                          requested_changes=[], summary="")
    with pytest.raises(TransactionRejected, match="ChangeSet"):
        SemanticTransaction(AnimaPlanAdapter()).execute(
            _plan(), malformed, current_revision=1)
    stale = ChangeSet(base_revision=0, plan_type="anima", intent_scope=["lighting"],
                      approved_requested_paths=["lighting"],
                      requested_changes=[_change("lighting", "noon")], summary="改光线")
    with pytest.raises(TransactionRejected, match="revision"):
        SemanticTransaction(AnimaPlanAdapter()).execute(
            _plan(), stale, current_revision=1)


def test_unresolved_conflict_and_semantic_failure_never_commit() -> None:
    changeset = ChangeSet(
        base_revision=1, plan_type="anima", intent_scope=["lighting"],
        approved_requested_paths=["lighting"],
        requested_changes=[_change("lighting", "noon")], summary="改光线",
        constraint_conflicts=[ConstraintConflict(
            path="lighting", constraint="locked", reason="光线被镜头连续性锁定")])
    with pytest.raises(TransactionRejected, match="约束冲突"):
        SemanticTransaction(AnimaPlanAdapter()).execute(
            _plan(), changeset, current_revision=1)
    changeset.constraint_conflicts = []
    with pytest.raises(TransactionRejected, match="语义校验"):
        SemanticTransaction(AnimaPlanAdapter()).execute(
            _plan(), changeset, current_revision=1,
            semantic_check=lambda _: ["forced failure"])


def test_missing_path_is_rejected_instead_of_creating_arbitrary_state() -> None:
    changeset = ChangeSet(
        base_revision=1, plan_type="anima", intent_scope=["characters/0/secret"],
        approved_requested_paths=["characters/0/secret"],
        requested_changes=[_change("characters/0/secret", "x")], summary="非法")
    with pytest.raises(TransactionRejected, match="无法应用变更"):
        SemanticTransaction(AnimaPlanAdapter()).execute(
            _plan(), changeset, current_revision=1)


def test_list_delete_authorizes_only_structural_index_shift() -> None:
    plan = _plan()
    plan.characters.append(AnimaCharacter(character_id="c2", action="running"))
    changeset = ChangeSet(
        base_revision=1, plan_type="anima", intent_scope=["characters/0"],
        approved_requested_paths=["characters/0"],
        requested_changes=[SemanticChange(
            path="characters/0", operation="delete", reason="用户删除第一个角色")],
        summary="删除第一个角色")
    result = SemanticTransaction(AnimaPlanAdapter()).execute(
        plan, changeset, current_revision=1)
    assert [character.character_id for character in result.plan.characters] == ["c2"]
    assert all(path.startswith("characters/") for path in result.changed_paths)


def test_impact_analyzer_cannot_mutate_stable_plan_even_when_it_fails() -> None:
    original = _plan()
    changeset = ChangeSet(
        base_revision=1, plan_type="anima", change_category="minimal_refine",
        intent_scope=["lighting"],
        approved_requested_paths=["lighting"],
        requested_changes=[_change("lighting", "noon")], summary="改光线")

    def corrupt_then_fail(plan: AnimaPromptPlan, proposed: ChangeSet) -> ChangeSet:
        plan.lighting = "corrupted"
        raise RuntimeError("impact failed")

    with pytest.raises(RuntimeError, match="impact failed"):
        SemanticTransaction(AnimaPlanAdapter()).execute(
            original, changeset, current_revision=1,
            impact_analyzer=corrupt_then_fail)
    assert original.lighting == "blue hour"


def test_transaction_enforces_plan_type_allowed_roots_locks_and_value_type() -> None:
    base = ChangeSet(
        base_revision=1, plan_type="minimax_h3", change_category="minimal_refine",
        intent_scope=["lighting"],
        approved_requested_paths=["lighting"],
        requested_changes=[_change("lighting", "noon")], summary="改光线")
    with pytest.raises(TransactionRejected, match="plan_type"):
        SemanticTransaction(AnimaPlanAdapter()).execute(
            _plan(), base, current_revision=1)

    base.plan_type = "anima"
    with pytest.raises(TransactionRejected, match="allowed root"):
        SemanticTransaction(AnimaPlanAdapter()).execute(
            _plan(), base, current_revision=1, allowed_roots=["characters"])
    with pytest.raises(TransactionRejected, match="locked"):
        SemanticTransaction(AnimaPlanAdapter()).execute(
            _plan(), base, current_revision=1, locked_paths=["lighting"])

    base.requested_changes[0].value = ["not", "a", "string"]
    with pytest.raises(TransactionRejected, match="value type"):
        SemanticTransaction(AnimaPlanAdapter()).execute(
            _plan(), base, current_revision=1, allowed_roots=["lighting"])


def test_transaction_rejects_immutable_metadata_and_magic_paths() -> None:
    for path in ("schema_version", "normal_form_version", "__class__/x"):
        changeset = ChangeSet(
            base_revision=1, plan_type="anima", change_category="minimal_refine",
            intent_scope=[path], approved_requested_paths=[path],
            requested_changes=[_change(path, "x")], summary="非法")
        with pytest.raises(TransactionRejected):
            SemanticTransaction(AnimaPlanAdapter()).execute(
                _plan(), changeset, current_revision=1)


def test_insert_requires_a_real_in_range_array_index() -> None:
    changeset = ChangeSet(
        base_revision=1, plan_type="anima", intent_scope=["characters"],
        approved_requested_paths=["characters"],
        requested_changes=[SemanticChange(
            path="characters/9", operation="insert",
            value=AnimaCharacter(character_id="c2").to_json(), reason="add")],
        summary="add character")
    with pytest.raises(TransactionRejected, match="索引"):
        SemanticTransaction(AnimaPlanAdapter()).execute(
            _plan(), changeset, current_revision=1, allowed_roots=["characters"])


def test_normalizer_changes_need_explicit_diff_guard_authorization() -> None:
    plan = _plan()
    plan.style = ["anime", "anime"]
    changeset = ChangeSet(
        base_revision=1, plan_type="anima", intent_scope=["lighting"],
        approved_requested_paths=["lighting"],
        requested_changes=[_change("lighting", "noon")], summary="lighting")
    transaction = SemanticTransaction(AnimaPlanAdapter())
    with pytest.raises(TransactionRejected, match="Diff Guard"):
        transaction.execute(plan, changeset, current_revision=1,
                            allowed_roots=["lighting"])
    result = transaction.execute(
        plan, changeset, current_revision=1, allowed_roots=["lighting"],
        normalization_paths=["style"])
    assert result.plan.style == ["anime"]


def test_normalizer_cannot_override_a_locked_path() -> None:
    plan = _plan()
    plan.style = ["anime", "anime"]
    changeset = ChangeSet(
        base_revision=1, plan_type="anima", intent_scope=["lighting"],
        approved_requested_paths=["lighting"],
        requested_changes=[_change("lighting", "noon")], summary="lighting")
    with pytest.raises(TransactionRejected, match="locked path"):
        SemanticTransaction(AnimaPlanAdapter()).execute(
            plan, changeset, current_revision=1, allowed_roots=["lighting"],
            locked_paths=["style"], normalization_paths=["style"])


def test_positive_change_deterministically_removes_matching_negative_constraint() -> None:
    content = _plan().to_json()
    state = ImageSemanticPlan(content=content, negative="hat, watermark")
    changeset = ChangeSet(
        base_revision=1, plan_type="anima", intent_scope=["content/supplemental_tags"],
        approved_requested_paths=["content/supplemental_tags"],
        requested_changes=[_change("content/supplemental_tags",
                                   ["black wide-brim hat"])],
        summary="add hat")
    result = SemanticTransaction(get_session_plan_adapter("anima")).execute(
        state, changeset, current_revision=1,
        impact_analyzer=analyze_image_impacts,
        semantic_check=validate_image_candidate,
        allowed_roots=["content", "negative"])
    assert result.plan.negative == "watermark"
    assert result.changeset.dependent_changes[0].path == "negative"


def test_h3_duration_change_deterministically_scales_timeline_cutpoints() -> None:
    plan = H3PromptPlan(duration_seconds=10.0, soundscape="room tone",
                        shots=[H3Shot(index=1), H3Shot(index=2, start_time=8.0)])
    changeset = ChangeSet(
        base_revision=1, plan_type="minimax_h3", intent_scope=["duration_seconds"],
        approved_requested_paths=["duration_seconds"],
        requested_changes=[_change("duration_seconds", 6.0)], summary="shorten")
    result = SemanticTransaction(H3PlanAdapter()).execute(
        plan, changeset, current_revision=1,
        impact_analyzer=analyze_h3_impacts,
        allowed_roots=["duration_seconds", "shots"])
    assert result.plan.duration_seconds == 6.0
    assert result.plan.shots[1].start_time == pytest.approx(4.8)
    assert result.changeset.dependent_changes[0].path == "shots/1/start_time"


def test_minimal_category_cannot_replace_a_broad_structural_root() -> None:
    changeset = ChangeSet(
        base_revision=1, plan_type="anima", change_category="minimal_refine",
        intent_scope=["characters"],
        approved_requested_paths=["characters"],
        requested_changes=[_change("characters", [])], summary="replace all")
    with pytest.raises(TransactionRejected, match="change category"):
        SemanticTransaction(AnimaPlanAdapter()).execute(
            _plan(), changeset, current_revision=1, allowed_roots=["characters"],
            broad_only_roots=["characters"])


def test_broad_rewrite_requires_independent_user_authorization() -> None:
    changeset = ChangeSet(
        base_revision=1, plan_type="anima", change_category="broad_rewrite",
        intent_scope=["characters"],
        approved_requested_paths=["characters"],
        requested_changes=[_change("characters", [])], summary="rebuild")
    transaction = SemanticTransaction(AnimaPlanAdapter())
    with pytest.raises(TransactionRejected, match="broad_rewrite"):
        transaction.execute(_plan(), changeset, current_revision=1,
                            allowed_roots=["characters"],
                            broad_only_roots=["characters"])
    result = transaction.execute(
        _plan(), changeset, current_revision=1, allowed_roots=["characters"],
        broad_only_roots=["characters"], allow_broad=True)
    assert result.plan.characters == []


def test_changeset_rejects_duplicate_operations_on_one_path() -> None:
    changeset = ChangeSet(
        base_revision=1, plan_type="anima", intent_scope=["lighting"],
        approved_requested_paths=["lighting"],
        requested_changes=[_change("lighting", "noon")],
        dependent_changes=[_change("lighting", "night", "dependency")],
        summary="conflicting operations")
    with pytest.raises(TransactionRejected, match="同一路径"):
        SemanticTransaction(AnimaPlanAdapter()).execute(
            _plan(), changeset, current_revision=1)


def test_unapproved_model_dependent_change_is_denied() -> None:
    changeset = ChangeSet(
        base_revision=1, plan_type="anima", intent_scope=["lighting"],
        approved_requested_paths=["lighting"],
        requested_changes=[_change("lighting", "noon")],
        dependent_changes=[_change("characters/0/action", "dancing",
                                   "model claimed dependency")],
        summary="lighting plus unrelated action")
    with pytest.raises(TransactionRejected, match="Impact Analysis"):
        SemanticTransaction(AnimaPlanAdapter()).execute(
            _plan(), changeset, current_revision=1)


def test_unapproved_requested_change_is_denied_even_if_self_scoped() -> None:
    changeset = ChangeSet(
        base_revision=1, plan_type="anima", intent_scope=["lighting"],
        requested_changes=[_change("lighting", "noon")], summary="lighting")
    with pytest.raises(TransactionRejected, match="Intent Grounding"):
        SemanticTransaction(AnimaPlanAdapter()).execute(
            _plan(), changeset, current_revision=1)


def test_negative_change_cannot_falsely_claim_positive_conflict_is_resolved() -> None:
    state = ImageSemanticPlan(content=_plan().to_json(),
                              negative="hat, watermark")
    changeset = ChangeSet(
        base_revision=1, plan_type="anima",
        intent_scope=["content/supplemental_tags"],
        approved_requested_paths=["content/supplemental_tags"],
        approved_dependent_paths=["negative"],
        requested_changes=[_change("content/supplemental_tags",
                                   ["black wide-brim hat"])],
        dependent_changes=[_change("negative", "hat, low quality",
                                   "claimed conflict cleanup")],
        summary="add hat")
    with pytest.raises(TransactionRejected, match="语义校验"):
        SemanticTransaction(get_session_plan_adapter("anima")).execute(
            state, changeset, current_revision=1,
            impact_analyzer=analyze_image_impacts,
            semantic_check=validate_image_candidate,
            allowed_roots=["content", "negative"])

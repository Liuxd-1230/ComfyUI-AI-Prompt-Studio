from __future__ import annotations

from aps.domain.plan_adapters import AnimaPlanAdapter, H3PlanAdapter
from aps.domain.semantic_consistency import (
    SemanticConsistencyPipeline, analyze_anima_impacts, assess_risk, deterministic_h3_repair,
    validate_anima_semantics, validate_h3_semantics)
from aps.schemas.anima import AnimaCharacter, AnimaPromptPlan
from aps.schemas.changeset import ChangeSet, SemanticChange
from aps.schemas.h3 import H3Dialogue, H3PromptPlan, H3Shot, H3Speaker
from aps.schemas.semantic import SemanticIssue
from aps.domain.transactions import SemanticTransaction, TransactionRejected
from aps.domain.gateway_critic import GatewaySemanticCritic
from aps.schemas.profile import AIProfile
from aps.schemas.results import LLMResult
import pytest


def _changeset(path: str) -> ChangeSet:
    return ChangeSet(base_revision=1, intent_scope=[path],
                     requested_changes=[SemanticChange(
                         path=path, value="x", reason="用户明确要求")],
                     summary="test")


def test_risk_classifier_only_requires_critic_for_high_impact_paths() -> None:
    assert assess_risk(_changeset("style/0")).critic_required is False
    high = assess_risk(_changeset("shots/1/dialogues/0/text"))
    assert high.level == "high"
    assert high.critic_required is True


def test_low_risk_skips_critic_and_high_risk_invokes_it_once() -> None:
    plan = AnimaPromptPlan(scene_description="a street")
    calls: list[int] = []

    def critic(_plan, _changeset):
        calls.append(1)
        return []

    pipeline = SemanticConsistencyPipeline(AnimaPlanAdapter(),
                                           validate_anima_semantics)
    low = pipeline.run(plan, _changeset("style/0"), critic=critic)
    assert low.critic_invoked is False
    assert calls == []
    high = pipeline.run(plan, _changeset("characters/0/action"), critic=critic)
    assert high.critic_invoked is True
    assert calls == [1]


def test_anima_detects_identity_ownership_and_positive_negative_conflict() -> None:
    plan = AnimaPromptPlan(
        characters=[AnimaCharacter(
            character_id="c1", required_traits=["blue eyes"],
            variable_traits=["blue eyes"])],
        negative_constraints=["no blue eyes"])
    codes = {issue.code for issue in validate_anima_semantics(plan)}
    assert codes == {"anima_trait_ownership", "anima_positive_negative_conflict"}


def test_anima_pnf_needs_no_derived_prose_cleanup_and_blocks_stale_lighting() -> None:
    plan = AnimaPromptPlan(
        scene_description="street", environment=["street"], lighting="neon",
        characters=[AnimaCharacter(character_id="c1")])
    trait_change = ChangeSet(
        base_revision=1, intent_scope=["character.action"],
        requested_changes=[SemanticChange(
            path="characters/0/action", value="running", reason="用户要求")],
        summary="改动作")
    result = SemanticTransaction(AnimaPlanAdapter()).execute(
        plan, trait_change, current_revision=1, impact_analyzer=analyze_anima_impacts)
    assert result.plan.characters[0].action == "running"
    assert result.changeset.dependent_changes == []

    environment_change = ChangeSet(
        base_revision=1, intent_scope=["environment"],
        requested_changes=[SemanticChange(
            path="environment", value=["beach"], reason="用户要求")],
        summary="换场景")
    with pytest.raises(TransactionRejected, match="失效事实"):
        SemanticTransaction(AnimaPlanAdapter()).execute(
            plan, environment_change, current_revision=1,
            impact_analyzer=analyze_anima_impacts)


def test_h3_priority_invariants_and_one_bounded_repair() -> None:
    plan = H3PromptPlan(
        mode="T2VA", duration_seconds=6, soundscape="room tone",
        speakers=[H3Speaker(speaker_id="S1")],
        shots=[H3Shot(index=4, start_time=1.0, dialogues=[H3Dialogue(
            speaker_ids=["S1"], kind="voiceover", lips_closed=False)])])
    changeset = _changeset("shots/0/dialogues/0/text")
    result = SemanticConsistencyPipeline(
        H3PlanAdapter(), validate_h3_semantics).run(
            plan, changeset, repairer=deterministic_h3_repair)
    assert result.repair_attempted is True
    assert result.repair_count == 1
    assert result.valid is True
    assert result.plan["shots"][0]["index"] == 1
    assert result.plan["shots"][0]["start_time"] is None
    assert result.plan["shots"][0]["dialogues"][0]["lips_closed"] is True


def test_repairer_is_never_retried_when_error_remains() -> None:
    plan = H3PromptPlan(mode="T2VA", duration_seconds=2, soundscape="",
                        shots=[H3Shot(index=9, start_time=1.0)])
    calls: list[int] = []

    def no_fix(candidate, _issues: list[SemanticIssue]):
        calls.append(1)
        return candidate

    # A repairable index issue triggers one pass, while duration/soundscape remain.
    result = SemanticConsistencyPipeline(H3PlanAdapter(), validate_h3_semantics).run(
        plan, _changeset("duration_seconds"), repairer=no_fix)
    assert result.valid is False
    assert result.repair_count == 1
    assert calls == [1]


def test_gateway_critic_is_a_real_structured_call_boundary() -> None:
    class FakeGateway:
        request = None

        def generate(self, _profile, _key, request):
            self.request = request
            return LLMResult(text='{"issues":[{"severity":"warning",'
                                  '"code":"camera_jump","path":"shots/1/camera",'
                                  '"message":"jump","reason":"continuity",'
                                  '"evidence":[],"repairable":false}]}')

    gateway = FakeGateway()
    critic = GatewaySemanticCritic(
        AIProfile(profile_id="p", model="m"), "k", gateway=gateway)
    issues = critic(H3PromptPlan(duration_seconds=6, soundscape="room"),
                    _changeset("shots/1/camera"))
    assert issues[0].code == "camera_jump"
    assert gateway.request.output_schema
    assert gateway.request.assembly_report["task_data_ids"] == (
        "current_plan", "changeset")

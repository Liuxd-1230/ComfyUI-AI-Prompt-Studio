from __future__ import annotations

from aps.domain.plan_adapters import AnimaPlanAdapter, H3PlanAdapter
from aps.domain.semantic_consistency import (
    SemanticConsistencyPipeline, analyze_anima_impacts, assert_repair_scope, assess_risk,
    validate_anima_semantics, validate_h3_semantics)
from aps.schemas.anima import AnimaCharacter, AnimaPromptPlan
from aps.schemas.changeset import ChangeSet, SemanticChange
from aps.schemas.h3 import H3Dialogue, H3PromptPlan, H3Shot, H3Speaker
from aps.schemas.image_semantic_plan import ImageSemanticPlan
from aps.domain.transactions import SemanticTransaction, TransactionRejected
from aps.domain.gateway_critic import GatewaySemanticCritic
from aps.schemas.profile import AIProfile
from aps.schemas.results import LLMResult
import pytest


def _changeset(path: str) -> ChangeSet:
    return ChangeSet(base_revision=1, plan_type="anima", intent_scope=[path],
                     approved_requested_paths=[path],
                     requested_changes=[SemanticChange(
                         path=path, value="x", reason="用户明确要求")],
                     summary="test")


def test_risk_classifier_only_requires_critic_for_high_impact_paths() -> None:
    simple_style = _changeset("style/0")
    simple_style.requested_changes[0].value = "watercolor"
    assert assess_risk(simple_style).critic_required is False
    assert assess_risk(_changeset("style/0")).critic_required is True
    assert assess_risk(
        _changeset("content/characters/0/variable_traits/0")).critic_required is False
    high = assess_risk(_changeset("shots/1/action"))
    assert high.level == "high"
    assert high.critic_required is True
    assert assess_risk(_changeset("negative")).critic_required is False
    broad_negative = _changeset("negative")
    broad_negative.requested_changes[0].value = "hat, watermark, extra fingers"
    assert assess_risk(broad_negative).critic_required is True
    assert assess_risk(_changeset("content/lighting")).critic_required is False
    assert assess_risk(_changeset("content/composition")).critic_required is False
    assert assess_risk(_changeset("content/characters/0/required_traits/0")).critic_required is True
    structural = _changeset("content/characters/0")
    structural.requested_changes[0].operation = "delete"
    structural.requested_changes[0].value = None
    assert assess_risk(structural).critic_required is True


def test_low_risk_skips_critic_and_high_risk_invokes_it_once() -> None:
    plan = AnimaPromptPlan(scene_description="a street")
    calls: list[int] = []

    def critic(_plan, _changeset):
        calls.append(1)
        return []

    pipeline = SemanticConsistencyPipeline(AnimaPlanAdapter(),
                                           validate_anima_semantics)
    low_change = _changeset("style/0")
    low_change.requested_changes[0].value = "watercolor"
    low = pipeline.run(plan, low_change, critic=critic)
    assert low.critic_invoked is False
    assert calls == []
    high = pipeline.run(plan, _changeset("characters/0/action"), critic=critic)
    assert high.critic_invoked is True
    assert calls == [1]


def test_consistency_result_reports_the_actual_repair_attempt() -> None:
    result = SemanticConsistencyPipeline(
        AnimaPlanAdapter(), validate_anima_semantics).run(
            AnimaPromptPlan(scene_description="street"),
            _changeset("lighting"), repair_count=1)
    assert result.repair_attempted is True
    assert result.repair_count == 1


def test_high_risk_pipeline_never_silently_skips_missing_critic() -> None:
    pipeline = SemanticConsistencyPipeline(
        H3PlanAdapter(), validate_h3_semantics)
    with pytest.raises(ValueError, match="Critic"):
        pipeline.run(
            H3PromptPlan(duration_seconds=6, soundscape="room tone"),
            _changeset("shots/0/action"))


def test_anima_detects_identity_ownership_and_positive_negative_conflict() -> None:
    plan = AnimaPromptPlan(
        characters=[AnimaCharacter(
            character_id="c1", required_traits=["blue eyes"],
            variable_traits=["blue eyes"])],
        negative_constraints=["no blue eyes"])
    codes = {issue.code for issue in validate_anima_semantics(plan)}
    assert codes == {"anima_trait_ownership", "anima_positive_negative_conflict"}


def test_anima_deterministically_rejects_unqualified_style_conflict() -> None:
    issues = validate_anima_semantics(AnimaPromptPlan(
        style=["photorealistic", "anime"]))
    assert {issue.code for issue in issues} == {"anima_style_conflict"}


def test_h3_deterministically_checks_visible_speaker_binding() -> None:
    plan = H3PromptPlan(
        mode="T2VA", duration_seconds=6, soundscape="room tone",
        speakers=[H3Speaker(speaker_id="S1")],
        shots=[H3Shot(index=1, characters=[], dialogues=[H3Dialogue(
            speaker_ids=["S1"], kind="speech", text="hello")])])
    codes = {issue.code for issue in validate_h3_semantics(plan)}
    assert "h3_speaker_not_visible" in codes


def test_anima_pnf_needs_no_derived_prose_cleanup_and_blocks_stale_lighting() -> None:
    plan = AnimaPromptPlan(
        scene_description="street", environment=["street"], lighting="neon",
        characters=[AnimaCharacter(character_id="c1")])
    trait_change = ChangeSet(
        base_revision=1, plan_type="anima", intent_scope=["characters/0/action"],
        approved_requested_paths=["characters/0/action"],
        requested_changes=[SemanticChange(
            path="characters/0/action", value="running", reason="用户要求")],
        summary="改动作")
    result = SemanticTransaction(AnimaPlanAdapter()).execute(
        plan, trait_change, current_revision=1, impact_analyzer=analyze_anima_impacts)
    assert result.plan.characters[0].action == "running"
    assert result.changeset.dependent_changes == []

    environment_change = ChangeSet(
        base_revision=1, plan_type="anima", intent_scope=["environment"],
        approved_requested_paths=["environment"],
        requested_changes=[SemanticChange(
            path="environment", value=["beach"], reason="用户要求")],
        summary="换场景")
    with pytest.raises(TransactionRejected, match="失效事实"):
        SemanticTransaction(AnimaPlanAdapter()).execute(
            plan, environment_change, current_revision=1,
            impact_analyzer=analyze_anima_impacts)


def test_h3_priority_invariants_are_reported_without_mutating_candidate() -> None:
    plan = H3PromptPlan(
        mode="T2VA", duration_seconds=6, soundscape="room tone",
        speakers=[H3Speaker(speaker_id="S1")],
        shots=[H3Shot(index=4, start_time=1.0, dialogues=[H3Dialogue(
            speaker_ids=["S1"], kind="voiceover", lips_closed=False)])])
    changeset = _changeset("shots/0/dialogues/0/text")
    result = SemanticConsistencyPipeline(H3PlanAdapter(), validate_h3_semantics).run(
        plan, changeset, critic=lambda _plan, _changes: [])
    assert result.valid is False
    assert result.repair_attempted is False
    assert result.plan["shots"][0]["index"] == 4
    assert result.plan["shots"][0]["start_time"] == 1.0


def test_h3_detects_explicit_drop_to_hold_gap_but_allows_pickup_transition() -> None:
    broken = H3PromptPlan(mode="T2VA", duration_seconds=6, soundscape="room", shots=[
        H3Shot(index=1, description=["She drops the umbrella."]),
        H3Shot(index=2, start_time=3, description=["She holds the umbrella."]),
    ])
    assert "h3_object_state_gap" in {
        issue.code for issue in validate_h3_semantics(broken)}
    broken.shots[1].description = ["She picks up and holds the umbrella."]
    assert "h3_object_state_gap" not in {
        issue.code for issue in validate_h3_semantics(broken)}


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
    plan = H3PromptPlan(duration_seconds=6, soundscape="room", shots=[
        H3Shot(index=1, description=["near zero"]),
        H3Shot(index=2, description=["affected"]),
        H3Shot(index=3, description=["near two"]),
        H3Shot(index=4, description=["DISTANT_SECRET"]),
    ])
    issues = critic(plan, _changeset("shots/1/camera"),
                    hard_constraints=["mode", "duration_seconds"])
    assert issues[0].code == "camera_jump"
    assert gateway.request.output_schema
    assert gateway.request.assembly_report["task_data_ids"] == (
        "current_plan", "changeset", "hard_constraints")
    sent = gateway.request.messages[0].content
    assert "affected" in sent and "near zero" in sent and "near two" in sent
    assert "DISTANT_SECRET" not in sent


def test_gateway_critic_rejects_semantically_malformed_issue_payload() -> None:
    class BadGateway:
        def generate(self, _profile, _key, _request):
            return LLMResult(text='{"issues":[{"severity":"maybe","code":"",'
                                  '"path":"","message":"","reason":"",'
                                  '"evidence":[],"repairable":"yes"}]}')

    critic = GatewaySemanticCritic(
        AIProfile(profile_id="p", model="m"), "k", gateway=BadGateway())
    with pytest.raises(ValueError, match="issue"):
        critic(H3PromptPlan(duration_seconds=6, soundscape="room"),
               _changeset("shots/0/action"))


def test_image_critic_slice_contains_binding_and_negative_dependencies() -> None:
    class CaptureGateway:
        request = None

        def generate(self, _profile, _key, request):
            self.request = request
            return LLMResult(text='{"issues":[]}')

    gateway = CaptureGateway()
    critic = GatewaySemanticCritic(
        AIProfile(profile_id="p", model="m"), "k", gateway=gateway)
    plan = ImageSemanticPlan(content={"characters": [
        {"character_id": "alice", "action": "standing", "position": "left"},
        {"character_id": "bob", "action": "sitting", "position": "right"},
    ], "environment": ["cafe"]}, negative="hat")
    critic(plan, _changeset("content/characters/0/action"))
    sent = gateway.request.messages[0].content
    assert "alice" in sent and "bob" in sent
    assert '"negative":"hat"' in sent


def test_repair_scope_rejects_unrelated_sibling_and_wildcard_expansion() -> None:
    repair = _changeset("shots/1/description")
    with pytest.raises(ValueError, match="无关的路径"):
        assert_repair_scope(repair, ["shots/1/camera_amplitude"])
    with pytest.raises(ValueError, match="无关的路径"):
        assert_repair_scope(repair, ["shots/*/references"])

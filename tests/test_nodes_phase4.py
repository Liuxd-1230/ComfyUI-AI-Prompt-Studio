"""节点层测试：Storyboard Builder 与 Prompt Composer（LLM mock / 确定性渲染）。"""
import json

import pytest

import aps.nodes.prompt_composer as pc_mod
import aps.nodes.storyboard_builder as sb_mod
from aps.schemas.character import CharacterBible
from aps.schemas.prompt_plan import PromptPlan
from aps.schemas.results import LLMResult
from aps.schemas.storyboard import Storyboard


def setup_profile(store):
    store.create_profile({"profile_id": "p1", "name": "DeepSeek"})
    store.set_api_key("p1", "sk-abcdef1234567890")
    return store.get_profile("p1").node_payload()


STORYBOARD_JSON = {
    "title": "咖啡店",
    "characters": ["c1"],
    "scenes": [{"scene_id": "s1", "title": "进门", "location": "咖啡店",
                "synopsis": "少女走进", "characters": ["c1"],
                "shots": [{"shot_id": "s1sh1", "summary": "全景", "action": "推门",
                           "camera": "wide", "duration": 3.0,
                           "characters": ["c1"]}]}],
}


# ------------------------------------------------------------------ Storyboard Builder

class FakeGateway:
    def __init__(self, text):
        self.text = text

    def generate(self, profile, api_key, req):
        return LLMResult(text=self.text)


def test_storyboard_builder_full(monkeypatch, store):
    payload = setup_profile(store)
    monkeypatch.setattr(sb_mod, "Gateway",
                        lambda: FakeGateway(json.dumps(STORYBOARD_JSON)))
    node = sb_mod.APS_StoryboardBuilder()
    sb_json, summary, continuity = node.build(
        AI_PROFILE=payload, story_text="少女走进咖啡店。",
        split_mode="scene", target_duration=10.0, max_scenes=6,
        style="Cinematic", character_bible=None, reference_manifest=None)
    sb = Storyboard.from_json(sb_json)
    assert sb.title == "咖啡店"
    assert len(sb.scenes) == 1
    assert sb.scenes[0].shots[0].action == "推门"
    assert sb.summary.startswith("少女走进")
    assert json.loads(continuity) == []  # 单场景无连续性提示


def test_storyboard_builder_empty_text(store):
    payload = setup_profile(store)
    node = sb_mod.APS_StoryboardBuilder()
    with pytest.raises(ValueError, match="为空"):
        node.build(AI_PROFILE=payload, story_text="", split_mode="scene",
                   target_duration=10.0, max_scenes=6, style="",
                   character_bible=None, reference_manifest=None)


def test_storyboard_builder_invalid_model_output(monkeypatch, store):
    payload = setup_profile(store)
    monkeypatch.setattr(sb_mod, "Gateway", lambda: FakeGateway("不是 JSON"))
    node = sb_mod.APS_StoryboardBuilder()
    with pytest.raises(ValueError, match="JSON"):
        node.build(AI_PROFILE=payload, story_text="故事",
                   split_mode="scene", target_duration=10.0, max_scenes=6,
                   style="", character_bible=None, reference_manifest=None)


# ------------------------------------------------------------------ Prompt Composer

def test_composer_anima_generate_deterministic(store):
    payload = setup_profile(store)
    node = pc_mod.APS_PromptComposer()
    positive, negative, plan_json, profile_json, validation = node.compose(
        AI_PROFILE=payload, text="1girl, long hair, red dress", target="anima_base",
        operation="generate", prompt_mode="tags", negative="", content_tier="safe",
        story_item=None, character_bible=None, reference_manifest=None,
        skill="", lora_triggers="")
    assert positive.startswith("masterpiece, best quality, score_7, safe, ")
    assert "score_1" in negative
    plan = PromptPlan.from_json(plan_json)
    assert plan.target_family == "anima" and plan.target_variant == "base"
    assert plan.validation.valid is True
    import aps.schemas.prompt_plan as PP

    prof = PP.GenerationProfile.from_json(profile_json)
    assert prof.steps == 40 and prof.cfg == 5.0


def test_composer_anima_aesthetic_no_score(store):
    payload = setup_profile(store)
    node = pc_mod.APS_PromptComposer()
    positive, negative, _, profile_json, validation = node.compose(
        AI_PROFILE=payload, text="1girl", target="anima_aesthetic",
        operation="generate", prompt_mode="tags", negative="",
        content_tier="safe", story_item=None, character_bible=None,
        reference_manifest=None, skill="", lora_triggers="")
    assert "score_" not in positive
    assert "score_" not in negative
    assert positive.startswith("masterpiece, best quality, safe, ")


def test_composer_anima_turbo_profile(store):
    payload = setup_profile(store)
    node = pc_mod.APS_PromptComposer()
    _, _, _, profile_json, _ = node.compose(
        AI_PROFILE=payload, text="1girl", target="anima_turbo",
        operation="generate", prompt_mode="tags", negative="",
        content_tier="safe", story_item=None, character_bible=None,
        reference_manifest=None, skill="", lora_triggers="")
    import aps.schemas.prompt_plan as PP

    prof = PP.GenerationProfile.from_json(profile_json)
    assert prof.cfg == 1.0 and prof.steps == 10


def test_composer_expand_uses_skill(monkeypatch, store):
    payload = setup_profile(store)
    monkeypatch.setattr(pc_mod, "Gateway",
                        lambda: FakeGateway("1girl, long hair, cafe interior"))
    node = pc_mod.APS_PromptComposer()
    positive, _, plan_json, _, _ = node.compose(
        AI_PROFILE=payload, text="少女走进咖啡店", target="anima_base",
        operation="expand", prompt_mode="tags", negative="",
        content_tier="safe", story_item=None, character_bible=None,
        reference_manifest=None, skill="", lora_triggers="")
    assert positive.startswith("masterpiece")
    assert "cafe interior" in positive


def test_composer_audit_only(store):
    payload = setup_profile(store)
    node = pc_mod.APS_PromptComposer()
    positive, negative, plan_json, _, validation = node.compose(
        AI_PROFILE=payload, text="Long_Hair, 1girl, 1girl", target="anima_base",
        operation="audit", prompt_mode="tags", negative="",
        content_tier="safe", story_item=None, character_bible=None,
        reference_manifest=None, skill="", lora_triggers="")
    assert "anima_uppercase" in validation
    assert "anima_duplicate" in validation


def test_composer_custom_skill_missing(store):
    payload = setup_profile(store)
    node = pc_mod.APS_PromptComposer()
    with pytest.raises(ValueError, match="Skill 不存在"):
        node.compose(AI_PROFILE=payload, text="x", target="custom_skill",
                     operation="generate", prompt_mode="tags", negative="",
                     content_tier="safe", story_item=None, character_bible=None,
                     reference_manifest=None, skill="nope", lora_triggers="")


def test_composer_empty_input(store):
    payload = setup_profile(store)
    node = pc_mod.APS_PromptComposer()
    with pytest.raises(ValueError, match="为空"):
        node.compose(AI_PROFILE=payload, text="", target="anima_base",
                     operation="generate", prompt_mode="tags", negative="",
                     content_tier="safe", story_item=None, character_bible=None,
                     reference_manifest=None, skill="", lora_triggers="")

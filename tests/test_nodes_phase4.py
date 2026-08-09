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
    sb_json, summary, continuity = node.build(
        AI_PROFILE=payload, story_text="少女走进咖啡馆。",
        split_mode="scene", target_duration=10.0, max_scenes=6,
        style="", character_bible=None, reference_manifest=None)
    sb = Storyboard.from_json(sb_json)
    assert len(sb.scenes) == 1 and len(sb.scenes[0].shots) == 1
    assert sb.scenes[0].shots[0].summary == "少女走进咖啡馆。"
    assert any(item["severity"] == "warning" and "JSON" in item["note"]
               for item in json.loads(continuity))


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


def test_composer_persistent_create_then_minimal_refine(monkeypatch, store):
    payload = setup_profile(store)
    node = pc_mod.APS_PromptComposer()
    created = node.compose(
        AI_PROFILE=payload, text="1girl, red dress, tokyo rain", target="anima_base",
        operation="generate", prompt_mode="tags", negative="", safety_tag="none")
    session_json = created["ui"]["prompt_session"][0]
    # Simulate ComfyUI writing the hidden widget into workflow JSON, closing the
    # graph, and constructing a fresh node from the serialized workflow value.
    workflow_json = json.dumps({"nodes": [{"widgets_values": {
        "prompt_session": session_json}}]}, ensure_ascii=False)
    session_json = json.loads(workflow_json)["nodes"][0]["widgets_values"]["prompt_session"]
    node = pc_mod.APS_PromptComposer()
    session_v1 = json.loads(session_json)
    old_negative = session_v1["current_plan"]["prompt_plan"]["negative"]

    class PatchGateway:
        req = None

        def generate(self, profile, api_key, req):
            PatchGateway.req = req
            return LLMResult(text=json.dumps({
                "base_revision": 1, "scope": "minimal",
                "changes": [{"path": "model_plan/content/visual_tags/1", "action": "replace",
                             "value": "white dress"}],
                "summary": "已把红裙改为白裙，其他内容保持不变。",
            }))

    monkeypatch.setattr(pc_mod, "Gateway", PatchGateway)
    refined = node.compose(
        AI_PROFILE=payload, text="只把红裙改成白裙，其他不要动", target="anima_base",
        operation="generate", prompt_mode="tags", negative="", safety_tag="none",
        prompt_session=session_json, continue_previous=True)
    session_v2 = json.loads(refined["ui"]["prompt_session"][0])
    assert session_v2["revision"] == 2
    assert session_v2["current_plan"]["prompt_plan"]["negative"] == old_negative
    assert "white dress" in session_v2["current_prompt"]
    sent = PatchGateway.req.messages[0].content
    assert "current_plan" in sent and "latest_user_instruction" in sent
    assert "已把红裙" not in sent  # 不重放 AI 聊天 transcript

    reverted = node.compose(
        AI_PROFILE=payload, text="回退", target="anima_base", operation="generate",
        prompt_mode="tags", negative="", safety_tag="none",
        prompt_session=refined["ui"]["prompt_session"][0], session_action="previous")
    reverted_session = json.loads(reverted["ui"]["prompt_session"][0])
    assert reverted_session["revision"] == 1
    assert "red dress" in reverted_session["current_prompt"]


def test_composer_continue_off_starts_new_session(store):
    payload = setup_profile(store)
    node = pc_mod.APS_PromptComposer()
    first = node.compose(
        AI_PROFILE=payload, text="1girl, red dress", target="anima_base",
        operation="generate", prompt_mode="tags", negative="", safety_tag="none")
    first_session = json.loads(first["ui"]["prompt_session"][0])
    second = node.compose(
        AI_PROFILE=payload, text="1girl, blue coat", target="anima_base",
        operation="generate", prompt_mode="tags", negative="", safety_tag="none",
        prompt_session=first["ui"]["prompt_session"][0], continue_previous=False)
    second_session = json.loads(second["ui"]["prompt_session"][0])
    assert second_session["id"] != first_session["id"]
    assert second_session["revision"] == 1
    assert "blue coat" in second_session["current_prompt"]


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


def test_switching_custom_skill_starts_a_new_session(monkeypatch, store):
    from types import SimpleNamespace
    from aps.schemas.prompt_plan import GenerationProfile

    payload = setup_profile(store)
    skills = {
        "one": SimpleNamespace(id="one", renderer="generic", target_family="generic",
                               target_variant="one", validators=[]),
        "two": SimpleNamespace(id="two", renderer="generic", target_family="generic",
                               target_variant="two", validators=[]),
    }
    monkeypatch.setattr(pc_mod, "get_skill", lambda skill_id: skills.get(skill_id))
    monkeypatch.setattr(
        pc_mod.APS_PromptComposer, "_skill_path",
        lambda self, prof, text, operation, prompt_mode, negative, bible, skill, lora:
        (f"{skill}: {text}", "", [], [], GenerationProfile(),
         {"clauses": [f"{skill}: {text}"]}))
    node = pc_mod.APS_PromptComposer()
    first = node.compose(payload, "first", "custom_skill", "generate",
                         "natural_language", "", skill="one")
    first_session = json.loads(first["ui"]["prompt_session"][0])
    second = node.compose(
        payload, "second", "custom_skill", "generate", "natural_language", "",
        skill="two", prompt_session=first["ui"]["prompt_session"][0])
    second_session = json.loads(second["ui"]["prompt_session"][0])
    assert second_session["id"] != first_session["id"]
    assert second_session["target_variant"] == "two"
    assert second_session["current_plan"]["model_plan"]["skill_id"] == "two"


def test_composer_rejects_h3_skill_wrong_consumer(store):
    payload = setup_profile(store)
    node = pc_mod.APS_PromptComposer()
    with pytest.raises(ValueError, match="H3 Director"):
        node.compose(AI_PROFILE=payload, text="x", target="custom_skill",
                     operation="generate", prompt_mode="natural_language", negative="",
                     safety_tag="none", story_item=None, character_bible=None,
                     reference_manifest=None, skill="minimax_h3_director",
                     lora_triggers="")


def test_composer_empty_input(store):
    payload = setup_profile(store)
    node = pc_mod.APS_PromptComposer()
    with pytest.raises(ValueError, match="为空"):
        node.compose(AI_PROFILE=payload, text="", target="anima_base",
                     operation="generate", prompt_mode="tags", negative="",
                     content_tier="safe", story_item=None, character_bible=None,
                     reference_manifest=None, skill="", lora_triggers="")

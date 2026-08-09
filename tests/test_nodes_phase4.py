"""节点层测试：Storyboard Builder 与 Prompt Composer（LLM mock / 确定性渲染）。"""
import json

import pytest

import aps.nodes.prompt_composer as pc_mod
import aps.nodes.storyboard_builder as sb_mod
from aps.schemas.character import CharacterBible, CharacterTrait
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


def test_composer_create_nonrepairable_semantic_error_skips_repair_and_commit(
        monkeypatch, store):
    payload = setup_profile(store)
    issue = pc_mod.SemanticIssue(
        severity="error", code="anima_identity_unprovable",
        path="content/characters/0/character_id",
        message="identity cannot be inferred", reason="missing stable source identity",
        repairable=False)
    monkeypatch.setattr(
        pc_mod, "_character_bible_semantic_issues",
        lambda content, bibles: [issue])
    repair_calls: list[int] = []
    commit_calls: list[int] = []

    def request_spy(*args, **kwargs):
        repair_calls.append(1)
        raise AssertionError("non-repairable CREATE must not request a repair")

    original_commit = pc_mod.PromptSession.commit

    def commit_spy(self, *args, **kwargs):
        commit_calls.append(1)
        return original_commit(self, *args, **kwargs)

    monkeypatch.setattr(pc_mod.APS_PromptComposer,
                        "_request_session_changeset", request_spy)
    monkeypatch.setattr(pc_mod.PromptSession, "commit", commit_spy)
    with pytest.raises(ValueError, match="不可自动修复") as exc_info:
        pc_mod.APS_PromptComposer().compose(
            AI_PROFILE=payload, text="1girl, red dress", target="anima_base",
            operation="generate", prompt_mode="tags", negative="",
            safety_tag="none")
    assert "identity cannot be inferred" in str(exc_info.value)
    assert repair_calls == []
    assert commit_calls == []


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
    legacy_content = session_v1["current_plan"]["model_plan"]["content"]
    legacy_content["normal_form_version"] = "1.0"
    legacy_content["natural_body"] = legacy_content.pop("scene_description")
    session_json = json.dumps(session_v1, ensure_ascii=False)
    old_negative = session_v1["current_plan"]["prompt_plan"]["negative"]

    class PatchGateway:
        req = None

        def generate(self, profile, api_key, req):
            if "approved_requested_paths" in (req.output_schema or {}).get("properties", {}):
                return LLMResult(text=json.dumps({
                    "approved_requested_paths": ["content/supplemental_tags/1"],
                    "approved_dependent_paths": [], "rejected_reasons": [],
                    "summary": "approved"}))
            PatchGateway.req = req
            return LLMResult(text=json.dumps({
                "base_revision": 1, "plan_type": "anima",
                "change_category": "minimal_refine",
                "intent_scope": ["content/supplemental_tags/1"],
                "requested_changes": [{"path": "content/supplemental_tags/1",
                    "operation": "set", "value_json": "\"white dress\"",
                    "reason": "user request"}],
                "dependent_changes": [], "invalidated_facts": [],
                "constraint_conflicts": [],
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
    migrated = session_v2["current_plan"]["model_plan"]["content"]
    assert migrated["normal_form_version"] == "2.0"
    assert "scene_description" in migrated and "natural_body" not in migrated
    assert "white dress" in session_v2["current_prompt"]
    sent = PatchGateway.req.messages[0].content
    assert "current_plan" in sent and "latest_user_instruction" in sent
    assert "supplemental_tags" in sent and "natural_body" not in sent
    assert '"prompt_plan"' not in sent
    assert '"generation_profile"' not in sent
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


def test_composer_stale_changeset_preserves_serialized_session(monkeypatch, store):
    payload = setup_profile(store)
    node = pc_mod.APS_PromptComposer()
    created = node.compose(
        AI_PROFILE=payload, text="1girl, red dress", target="anima_base",
        operation="generate", prompt_mode="tags", negative="", safety_tag="none")
    stable_json = created["ui"]["prompt_session"][0]
    stable = json.loads(stable_json)
    commit_calls = []
    original_commit = pc_mod.PromptSession.commit

    def commit_spy(self, *args, **kwargs):
        commit_calls.append(1)
        return original_commit(self, *args, **kwargs)

    monkeypatch.setattr(pc_mod.PromptSession, "commit", commit_spy)

    class StaleGateway:
        def generate(self, profile, api_key, req):
            if "approved_requested_paths" in (req.output_schema or {}).get("properties", {}):
                return LLMResult(text=json.dumps({
                    "approved_requested_paths": ["content/supplemental_tags/1"],
                    "approved_dependent_paths": [], "rejected_reasons": [],
                    "summary": "approved"}))
            return LLMResult(text=json.dumps({
                "base_revision": 0, "plan_type": "anima",
                "change_category": "minimal_refine",
                "intent_scope": ["content/supplemental_tags/1"],
                "requested_changes": [{"path": "content/supplemental_tags/1",
                    "operation": "set", "value_json": "\"blue dress\"",
                    "reason": "user request"}],
                "dependent_changes": [], "invalidated_facts": [],
                "constraint_conflicts": [], "summary": "stale"}))

    monkeypatch.setattr(pc_mod, "Gateway", StaleGateway)
    with pytest.raises(ValueError, match="revision"):
        node.compose(
            AI_PROFILE=payload, text="change dress", target="anima_base",
            operation="generate", prompt_mode="tags", negative="",
            safety_tag="none", prompt_session=stable_json, continue_previous=True)
    assert json.loads(stable_json)["revision"] == stable["revision"]
    assert json.loads(stable_json)["current_prompt"] == stable["current_prompt"]
    assert commit_calls == []


def test_composer_unresolved_positive_negative_impact_never_commits(monkeypatch, store):
    payload = setup_profile(store)
    node = pc_mod.APS_PromptComposer()
    created = node.compose(
        AI_PROFILE=payload, text="1girl, red dress", target="anima_base",
        operation="generate", prompt_mode="tags", negative="hat", safety_tag="none")
    stable_json = created["ui"]["prompt_session"][0]
    commit_calls = []
    original_commit = pc_mod.PromptSession.commit

    def commit_spy(self, *args, **kwargs):
        commit_calls.append(1)
        return original_commit(self, *args, **kwargs)

    monkeypatch.setattr(pc_mod.PromptSession, "commit", commit_spy)

    class ConflictGateway:
        def generate(self, profile, api_key, req):
            if "approved_requested_paths" in (req.output_schema or {}).get("properties", {}):
                return LLMResult(text=json.dumps({
                    "approved_requested_paths": ["content/supplemental_tags"],
                    "approved_dependent_paths": [], "rejected_reasons": [],
                    "summary": "approved"}))
            return LLMResult(text=json.dumps({
                "base_revision": 1, "plan_type": "anima",
                "change_category": "minimal_refine",
                "intent_scope": ["content/supplemental_tags"],
                "requested_changes": [{"path": "content/supplemental_tags",
                    "operation": "set", "value_json": "[\"black wide-brim hat\"]",
                    "reason": "user request"}],
                "dependent_changes": [], "invalidated_facts": [],
                "constraint_conflicts": [], "summary": "add hat"}))

    monkeypatch.setattr(pc_mod, "Gateway", ConflictGateway)
    with pytest.raises(ValueError, match="失效事实"):
        node.compose(
            AI_PROFILE=payload, text="add a black wide-brim hat",
            target="anima_base", operation="generate", prompt_mode="tags",
            negative="hat", safety_tag="none", prompt_session=stable_json)
    assert commit_calls == []


def test_composer_high_risk_critic_error_prevents_commit(monkeypatch, store):
    payload = setup_profile(store)
    node = pc_mod.APS_PromptComposer()
    created = node.compose(
        AI_PROFILE=payload, text="Alice in a red coat waits at a station",
        target="anima_base", operation="generate", prompt_mode="tags",
        negative="", safety_tag="none")
    stable_json = created["ui"]["prompt_session"][0]
    proposal = {
        "base_revision": 1, "plan_type": "anima",
        "change_category": "minimal_refine",
        "intent_scope": ["content/scene_description"],
        "requested_changes": [{"path": "content/scene_description",
            "operation": "set", "value_json": "\"Bob leaves the station\"",
            "reason": "user request"}],
        "dependent_changes": [], "invalidated_facts": [],
        "constraint_conflicts": [], "summary": "change scene action"}

    class CriticGateway:
        def generate(self, profile, api_key, req):
            properties = (req.output_schema or {}).get("properties", {})
            if "approved_requested_paths" in properties:
                return LLMResult(text=json.dumps({
                    "approved_requested_paths": ["content/scene_description"],
                    "approved_dependent_paths": [], "rejected_reasons": [],
                    "summary": "approved"}))
            if "issues" in properties:
                return LLMResult(text=json.dumps({"issues": [{
                    "severity": "error", "code": "image_identity_drift",
                    "path": "content/scene_description",
                    "message": "Alice was replaced by Bob",
                    "reason": "the user requested only an action change",
                    "evidence": ["Alice", "Bob"], "repairable": False}]}))
            return LLMResult(text=json.dumps(proposal))

    commit_calls = []
    original_commit = pc_mod.PromptSession.commit

    def commit_spy(self, *args, **kwargs):
        commit_calls.append(1)
        return original_commit(self, *args, **kwargs)

    monkeypatch.setattr(pc_mod.PromptSession, "commit", commit_spy)
    monkeypatch.setattr(pc_mod, "Gateway", CriticGateway)
    with pytest.raises(ValueError, match="Alice was replaced by Bob"):
        node.compose(
            AI_PROFILE=payload, text="只改动作，不要换人", target="anima_base",
            operation="generate", prompt_mode="tags", negative="",
            safety_tag="none", prompt_session=stable_json)
    assert commit_calls == []


def test_composer_persists_character_bible_identity_and_locked_trait_paths(store):
    payload = setup_profile(store)
    bible = CharacterBible(
        character_id="alice", name="Alice",
        traits=[CharacterTrait(name="eye_color", value="blue eyes",
                               category="stable", locked=True)])
    created = pc_mod.APS_PromptComposer().compose(
        AI_PROFILE=payload, text="Alice at a cafe", target="anima_base",
        operation="generate", prompt_mode="tags", negative="",
        safety_tag="none", character_bible=bible.to_json())
    session = json.loads(created["ui"]["prompt_session"][0])
    locks = session["locked_constraints"]
    assert any('"kind": "character_identity"' in value for value in locks)
    assert any('"kind": "character_trait"' in value and "blue eyes" in value
               for value in locks)


def test_composer_create_rejects_llm_that_drops_character_bible(monkeypatch, store):
    payload = setup_profile(store)
    bible = CharacterBible(
        character_id="alice", name="Alice",
        traits=[CharacterTrait(name="eye_color", value="blue eyes",
                               category="stable", locked=True)])
    wrong_plan = {
        "normal_form_version": "2.0", "scene_description": "A station platform",
        "characters": [{"character_id": "bob", "name": "Bob",
                        "required_traits": ["brown eyes"], "variable_traits": [],
                        "action": "waiting", "position": "", "creative_notes": []}],
    }
    monkeypatch.setattr(pc_mod, "Gateway",
                        lambda: FakeGateway(json.dumps(wrong_plan)))
    commit_calls = []
    original_commit = pc_mod.PromptSession.commit

    def commit_spy(self, *args, **kwargs):
        commit_calls.append(1)
        return original_commit(self, *args, **kwargs)

    monkeypatch.setattr(pc_mod.PromptSession, "commit", commit_spy)
    with pytest.raises(ValueError, match="Character Bible 人物 Alice 未进入正式 Plan"):
        pc_mod.APS_PromptComposer().compose(
            AI_PROFILE=payload, text="Alice waits at a station", target="anima_base",
            operation="generate", prompt_mode="natural_language", negative="",
            safety_tag="none", character_bible=bible.to_json())
    assert commit_calls == []


def test_value_addressed_trait_lock_survives_earlier_list_delete(monkeypatch, store):
    payload = setup_profile(store)
    bible = CharacterBible(character_id="alice", name="Alice", traits=[
        CharacterTrait(name="scarf", value="red scarf", category="stable"),
        CharacterTrait(name="eyes", value="blue eyes", category="stable", locked=True),
    ])
    created = pc_mod.APS_PromptComposer().compose(
        AI_PROFILE=payload, text="Alice at a cafe", target="anima_base",
        operation="generate", prompt_mode="tags", negative="", safety_tag="none",
        character_bible=bible.to_json())

    class DeleteUnlockedGateway:
        def generate(self, profile, api_key, req):
            properties = (req.output_schema or {}).get("properties", {})
            if "approved_requested_paths" in properties:
                return LLMResult(text=json.dumps({
                    "approved_requested_paths": [
                        "content/characters/0/required_traits/0"],
                    "approved_dependent_paths": [], "rejected_reasons": [],
                    "summary": "approved"}))
            if "issues" in properties:
                return LLMResult(text='{"issues":[]}')
            return LLMResult(text=json.dumps({
                "base_revision": 1, "plan_type": "anima",
                "change_category": "minimal_refine",
                "intent_scope": ["content/characters/0/required_traits/0"],
                "requested_changes": [{
                    "path": "content/characters/0/required_traits/0",
                    "operation": "delete", "value_json": "null",
                    "reason": "remove unlocked scarf"}],
                "dependent_changes": [], "invalidated_facts": [],
                "constraint_conflicts": [], "summary": "remove scarf"}))

    monkeypatch.setattr(pc_mod, "Gateway", DeleteUnlockedGateway)
    refined = pc_mod.APS_PromptComposer().compose(
        AI_PROFILE=payload, text="去掉围巾，眼睛保持不变", target="anima_base",
        operation="generate", prompt_mode="tags", negative="", safety_tag="none",
        prompt_session=created["ui"]["prompt_session"][0])
    session = json.loads(refined["ui"]["prompt_session"][0])
    traits = session["current_plan"]["model_plan"]["content"]["characters"][0][
        "required_traits"]
    assert traits == ["blue eyes"]
    assert any("blue eyes" in value for value in session["locked_constraints"])


def test_composer_rejects_ambiguous_v1_session_before_gateway(monkeypatch, store):
    payload = setup_profile(store)
    node = pc_mod.APS_PromptComposer()
    created = node.compose(
        AI_PROFILE=payload, text="1girl, red coat", target="anima_base",
        operation="generate", prompt_mode="tags", negative="", safety_tag="none")
    legacy = json.loads(created["ui"]["prompt_session"][0])
    content = legacy["current_plan"]["model_plan"]["content"]
    content["normal_form_version"] = "1.0"
    content.pop("scene_description", None)
    content["natural_body"] = "Alice wears a red coat."
    content["characters"] = [{
        "character_id": "c1", "name": "Alice",
        "required_traits": [], "variable_traits": ["red coat"],
        "action": "", "position": "",
    }]

    class ForbiddenGateway:
        def generate(self, profile, api_key, req):
            raise AssertionError("ambiguous migration must fail before an LLM patch")

    monkeypatch.setattr(pc_mod, "Gateway", ForbiddenGateway)
    with pytest.raises(ValueError, match="保持不变"):
        node.compose(
            AI_PROFILE=payload, text="change the coat", target="anima_base",
            operation="generate", prompt_mode="tags", negative="", safety_tag="none",
            prompt_session=json.dumps(legacy, ensure_ascii=False))
    assert legacy["revision"] == 1


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

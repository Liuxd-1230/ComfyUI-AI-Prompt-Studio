import json

import pytest

from aps.renderers.special_image import render_special_image
from aps.schemas.results import LLMResult


class PlainTextGateway:
    def generate(self, profile, api_key, req):
        return LLMResult(text="雨夜日式商店街，动漫少女撑透明伞回头，霓虹映在湿润路面。")


def test_z_image_contract_ignores_negative():
    result = render_special_image("a detailed scene", family="z_image",
                                  variant="turbo", negative_override="bad hands")
    assert result["negative"] == ""
    assert result["profile"].steps == 9
    assert result["profile"].cfg == 0.0
    assert any("忽略" in warning for warning in result["warnings"])


def test_qwen_contract_warns_about_raw_mentions():
    result = render_special_image("修改@图1", family="qwen_image_edit", variant="2511")
    assert result["negative"] == ""
    assert any("图片引用" in warning for warning in result["warnings"])


def test_composer_z_image_convert_is_offline(ext, store):
    store.create_profile({"profile_id": "local", "name": "Local"})
    ai_profile = ext.NODE_CLASS_MAPPINGS["APS_ModelProfile"]().resolve(
        profile="local", model_override="", protocol="auto", reasoning="medium",
        web_search="off", unload_policy="never")[0]
    positive, negative, plan, generation, validation = \
        ext.NODE_CLASS_MAPPINGS["APS_PromptComposer"]().compose(
            ai_profile, "a precise anime scene", "z_image_turbo", "convert",
            "natural_language", "bad anatomy")
    assert positive == "a precise anime scene"
    assert negative == ""
    assert plan["target_family"] == "z_image"
    assert generation["steps"] == 9 and generation["cfg"] == 0.0
    assert "通过" in validation


def test_composer_z_image_plain_text_response_does_not_commit(ext, store, monkeypatch):
    import aps.nodes.prompt_composer as composer_mod

    store.create_profile({"profile_id": "p1", "name": "Proxy"})
    store.set_api_key("p1", "sk-test-123456789")
    monkeypatch.setattr(composer_mod, "Gateway", PlainTextGateway)
    profile = store.get_profile("p1").node_payload()
    with pytest.raises(ValueError, match="结构化 Plan"):
        ext.NODE_CLASS_MAPPINGS["APS_PromptComposer"]().compose(
            profile, "雨夜商店街少女", "z_image_turbo", "generate",
            "natural_language", "")


def test_z_image_refine_patches_one_clause_and_preserves_others(ext, store, monkeypatch):
    import aps.nodes.prompt_composer as composer_mod

    store.create_profile({"profile_id": "z1", "name": "Z Planner"})
    store.set_api_key("z1", "sk-test-123456789")
    profile = store.get_profile("z1").node_payload()

    class CreateGateway:
        def generate(self, profile, api_key, req):
            return LLMResult(text=json.dumps({
                "positive": "a girl, red coat, Tokyo rain, wide shot"}))

    monkeypatch.setattr(composer_mod, "Gateway", CreateGateway)
    node = ext.NODE_CLASS_MAPPINGS["APS_PromptComposer"]()
    created = node.compose(profile, "雨夜街头女孩", "z_image_turbo", "generate",
                           "natural_language", "")
    session = json.loads(created["ui"]["prompt_session"][0])
    clauses = session["current_plan"]["model_plan"]["content"]["clauses"]
    assert len(clauses) == 4
    assert "".join(item["text"] + item["separator"] for item in clauses) == \
        "a girl, red coat, Tokyo rain, wide shot"

    class PatchGateway:
        def generate(self, profile, api_key, req):
            if "approved_requested_paths" in (req.output_schema or {}).get("properties", {}):
                return LLMResult(text=json.dumps({
                    "approved_requested_paths": ["content/clauses/1/text"],
                    "approved_dependent_paths": [], "rejected_reasons": [],
                    "summary": "approved"}))
            return LLMResult(text=json.dumps({
                "base_revision": 1, "plan_type": "z_image",
                "change_category": "minimal_refine",
                "intent_scope": ["content/clauses/1/text"],
                "requested_changes": [{"path": "content/clauses/1/text",
                    "operation": "set", "value_json": "\"white coat\"",
                    "reason": "user request"}],
                "dependent_changes": [], "invalidated_facts": [],
                "constraint_conflicts": [],
                "summary": "只把红外套改为白外套。"}))

    monkeypatch.setattr(composer_mod, "Gateway", PatchGateway)
    refined = node.compose(
        profile, "只把红外套改成白色，其他不变", "z_image_turbo", "generate",
        "natural_language", "", prompt_session=created["ui"]["prompt_session"][0])
    prompt = refined["result"][0]
    assert prompt == "a girl, white coat, Tokyo rain, wide shot"


def test_structured_prose_roundtrip_preserves_decimals_and_punctuation():
    import aps.nodes.prompt_composer as composer_mod

    original = "Use CFG 1.5. Keep Figure 1! 雨夜，霓虹。"
    content = composer_mod._text_content(original)
    assert composer_mod._content_body(content) == original

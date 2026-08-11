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


def test_prompt_studio_z_image_strict_refine_preserves_other_clauses(
        ext, store, monkeypatch):
    import aps.nodes.prompt_studio as studio_mod

    store.create_profile({"profile_id": "z1", "name": "Z Planner"})
    store.set_api_key("z1", "sk-test-123456789")
    profile = store.get_profile("z1").node_payload()

    class CreateGateway:
        def generate(self, profile, api_key, req):
            return LLMResult(text=json.dumps({
                "content": {"clauses": [
                    {"text": "a girl", "separator": ", "},
                    {"text": "red coat", "separator": ", "},
                    {"text": "Tokyo rain", "separator": ", "},
                    {"text": "wide shot", "separator": ""},
                ]}, "negative": ""}))

    monkeypatch.setattr(studio_mod, "Gateway", CreateGateway)
    node = ext.NODE_CLASS_MAPPINGS["APS_PromptStudio"]()
    created = node.run(profile, "雨夜街头女孩", "z_image_turbo", "strict")
    session = json.loads(created["ui"]["prompt_session"][0])
    clauses = session["current_plan"]["model_plan"]["content"]["clauses"]
    assert len(clauses) == 4
    assert "".join(item["text"] + item["separator"] for item in clauses) == \
        "a girl, red coat, Tokyo rain, wide shot"

    class PatchGateway:
        def generate(self, profile, api_key, req):
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

    monkeypatch.setattr(studio_mod, "Gateway", PatchGateway)
    refined = node.run(
        profile, "只把红外套改成白色，其他不变", "z_image_turbo", "strict",
        prompt_session=created["ui"]["prompt_session"][0], message_nonce="z2")
    prompt = refined["result"][0]
    assert prompt == "a girl, white coat, Tokyo rain, wide shot"

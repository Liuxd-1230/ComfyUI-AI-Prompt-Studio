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


def test_composer_z_image_plain_text_response_falls_back(ext, store, monkeypatch):
    import aps.nodes.prompt_composer as composer_mod

    store.create_profile({"profile_id": "p1", "name": "Proxy"})
    store.set_api_key("p1", "sk-test-123456789")
    monkeypatch.setattr(composer_mod, "Gateway", PlainTextGateway)
    profile = store.get_profile("p1").node_payload()
    positive, _, plan, _, validation = ext.NODE_CLASS_MAPPINGS["APS_PromptComposer"]().compose(
        profile, "雨夜商店街少女", "z_image_turbo", "generate",
        "natural_language", "")
    assert "透明伞" in positive
    assert any("JSON" in warning for warning in plan["warnings"])
    assert "warning" in validation

"""节点注册测试：分类、返回类型、输入结构。"""
import pytest

EXPECTED_NODES = [
    "APS_ModelProfile", "APS_LLMGenerate", "APS_ReferenceAnalyzer",
    "APS_CharacterBible", "APS_StoryboardBuilder", "APS_StoryboardSelect",
    "APS_PromptStudio", "APS_ReferencePrompt", "APS_H3PromptStudio", "APS_RuntimeControl",
    "APS_UnloadModel",
]


def test_all_nodes_registered(ext):
    mappings = ext.NODE_CLASS_MAPPINGS
    assert set(mappings.keys()) == set(EXPECTED_NODES)
    assert len(mappings) == 11


def test_display_names_present(ext):
    names = ext.NODE_DISPLAY_NAME_MAPPINGS
    for cls_name in EXPECTED_NODES:
        assert cls_name in names
        assert names[cls_name]


def test_every_node_shape(ext):
    for cls_name in EXPECTED_NODES:
        cls = ext.NODE_CLASS_MAPPINGS[cls_name]
        assert cls_name.startswith("APS_")
        assert cls.CATEGORY == "AI Prompt Studio", f"{cls_name} 分类错误"
        assert isinstance(cls.FUNCTION, str) and not callable(cls.FUNCTION)
        assert hasattr(cls, cls.FUNCTION), f"{cls_name} 缺少方法 {cls.FUNCTION}"
        assert cls.RETURN_TYPES, f"{cls_name} 缺少返回类型"
        assert len(cls.RETURN_TYPES) == len(cls.RETURN_NAMES), \
            f"{cls_name} RETURN_TYPES/RETURN_NAMES 长度不一致"
        input_types = cls.INPUT_TYPES()
        assert "required" in input_types, f"{cls_name} 缺少 required 输入"
        for w in input_types.get("optional", {}):
            assert input_types["optional"][w], f"{cls_name} optional 输入 {w} 缺类型"


def test_ai_profile_node_flow(ext, store):
    store.create_profile({"profile_id": "p1", "name": "DeepSeek", "model": "deepseek-v4-flash"})
    node = ext.NODE_CLASS_MAPPINGS["APS_ModelProfile"]()
    out = node.resolve(profile="p1", model_override="", protocol="auto",
                       reasoning="high", web_search="auto", unload_policy="never")
    assert len(out) == 1
    payload = out[0]
    assert payload["profile_id"] == "p1"
    assert payload["model"] == "deepseek-v4-flash"
    assert "api_key_ref" not in payload


def test_ai_profile_override(ext, store):
    store.create_profile({"profile_id": "p1"})
    node = ext.NODE_CLASS_MAPPINGS["APS_ModelProfile"]()
    out = node.resolve(profile="p1", model_override="other-model", protocol="responses",
                       reasoning="low", web_search="off", unload_policy="after_request")
    payload = out[0]
    assert payload["model"] == "other-model"
    assert payload["protocol"] == "responses"
    assert payload["reasoning"] == "low"
    assert payload["web_search"] == "off"
    assert payload["unload_policy"] == "after_request"


def test_ai_profile_missing_profile_readable_error(ext, store):
    node = ext.NODE_CLASS_MAPPINGS["APS_ModelProfile"]()
    with pytest.raises(ValueError, match="档案不存在"):
        node.resolve(profile="nope", model_override="", protocol="auto",
                     reasoning="high", web_search="auto", unload_policy="never")


def test_ai_profile_uses_profile_and_model_dropdowns(ext, store):
    store.create_profile({"profile_id": "p1", "name": "Proxy", "model": "model-a"})
    store.set_capabilities("p1", {"models": ["model-a", "model-b"]})
    inputs = ext.NODE_CLASS_MAPPINGS["APS_ModelProfile"].INPUT_TYPES()
    assert "Proxy [p1]" in inputs["required"]["profile"][0]
    assert "model-b" in inputs["required"]["model_override"][0]
    assert "custom_model_override" in inputs["optional"]


def test_ai_profile_named_choice_resolves_stable_id(ext, store):
    store.create_profile({"profile_id": "p_named", "name": "我的代理", "model": "model-a"})
    node = ext.NODE_CLASS_MAPPINGS["APS_ModelProfile"]()
    payload = node.resolve(profile="我的代理 [p_named]", model_override="", protocol="auto",
                           reasoning="medium", web_search="off", unload_policy="never")[0]
    assert payload["profile_id"] == "p_named"


def test_storyboard_select_node(ext, storyboard):
    node = ext.NODE_CLASS_MAPPINGS["APS_StoryboardSelect"]()
    item, item_list, scene_text, chars, batch, items = node.select(
        storyboard=storyboard.to_json(), select_mode="all",
        scene_id="", shot_id="", range="")
    assert batch == 3  # 三个镜头
    assert item_list["batch_count"] == 3
    assert item["kind"] == "shot"
    assert "c1" in json_loads(chars)

    item, item_list, scene_text, chars, batch, items = node.select(
        storyboard=storyboard.to_json(), select_mode="scene",
        scene_id="s2", shot_id="", range="")
    assert batch == 1 and item_list["items"][0]["scene_id"] == "s2"

    # 面向用户的序号与常见标签也必须可用，不能要求先猜模型生成的内部 ID。
    item, item_list, _, _, batch, _ = node.select(
        storyboard=storyboard.to_json(), select_mode="scene",
        scene_id="1", shot_id="", range="")
    assert batch == 1 and item_list["items"][0]["scene_id"] == "s1"

    item, item_list, _, _, batch, _ = node.select(
        storyboard=storyboard.to_json(), select_mode="shot",
        scene_id="", shot_id="shot_3", range="")
    assert batch == 1 and item_list["items"][0]["shot_id"] == "s2sh1"

    item, item_list, _, _, batch, items = node.select(
        storyboard=storyboard.to_json(), select_mode="range",
        scene_id="", shot_id="", range="1-2")
    assert batch == 2
    assert len(items) == 2

    item, item_list, _, _, batch, items = node.select(
        storyboard=storyboard.to_json(), select_mode="shot",
        scene_id="", shot_id="s2sh1", range="")
    assert batch == 1 and item_list["items"][0]["shot_id"] == "s2sh1"


def test_storyboard_select_invalid(ext, storyboard):
    node = ext.NODE_CLASS_MAPPINGS["APS_StoryboardSelect"]()
    with pytest.raises(ValueError):
        node.select(storyboard=storyboard.to_json(), select_mode="range",
                    scene_id="", shot_id="", range="9-99")
    with pytest.raises(ValueError):
        node.select(storyboard=storyboard.to_json(), select_mode="bogus",
                    scene_id="", shot_id="", range="")
    with pytest.raises(ValueError, match="可填写序号 1-2.*s1.*s2"):
        node.select(storyboard=storyboard.to_json(), select_mode="scene",
                    scene_id="99", shot_id="", range="")


def json_loads(s):
    import json

    return json.loads(s)

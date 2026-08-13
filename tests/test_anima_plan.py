"""ANIMA 结构化 Prompt Plan 回归测试：natural 默认、Bible 自然融入、Hybrid 不重复、多人物绑定。"""
import json
import pytest

from aps.renderers.anima import (
    AnimaCharacter,
    AnimaPromptPlan,
    build_anima_plan,
    parse_anima_plan,
    render_anima,
    render_anima_plan,
)
from aps.schemas.character import CharacterBible, CharacterTrait
from aps.schemas.base import SchemaError


def make_bible(name="少女", traits=None):
    bible = CharacterBible(name=name)
    for t in traits or []:
        bible.traits.append(CharacterTrait(**t))
    return bible


# ---------------------------------------------------------------- 默认模式

def test_default_prompt_mode_is_natural_language():
    r = render_anima("A girl sits beside a window under the rain.")
    assert r.positive.startswith("masterpiece")
    assert "A girl sits beside a window under the rain." in r.positive
    # natural 模式不出现机械 tag 段
    assert ", 1girl" not in r.positive


def test_current_anima_plan_rejects_string_in_list_field() -> None:
    with pytest.raises(SchemaError, match="style 必须是数组"):
        AnimaPromptPlan.from_json({
            "normal_form_version": "2.0",
            "style": "cinematic",
        })


# ---------------------------------------------------------------- Bible 自然融入

def test_natural_mode_consumes_bible_traits():
    bible = make_bible("A young woman", [
        {"name": "hair", "value": "long straight black hair", "category": "stable", "locked": True},
        {"name": "face", "value": "a soft round face", "category": "stable"},
        {"name": "mark", "value": "a small mole below her left eye", "category": "stable"},
        {"name": "clothing", "value": "a red evening dress", "category": "variable"},
    ])
    r = render_anima("She sits beside the window.", bible=bible,
                     prompt_mode="natural_language")
    # 锁定/稳定身份特征进入正文（自然句，而非 tag 列表）
    assert "long straight black hair" in r.positive
    assert "soft round face" in r.positive
    assert "mole below her left eye" in r.positive
    assert "red evening dress" in r.positive
    assert "She sits beside the window." in r.positive
    # 不是 tag soup：逗号分隔的裸标签列表不应存在
    assert r.positive.count("long straight black hair") == 1


def test_natural_mode_dedupes_bible_traits_already_in_body():
    bible = make_bible("A young woman", [
        {"name": "hair", "value": "long dark hair", "category": "stable", "locked": True}])
    r = render_anima("A young woman with long dark hair walks in the rain.",
                     bible=bible, prompt_mode="natural_language")
    assert r.positive.count("long dark hair") == 1


def test_natural_dedup_phrase_within_longer_sentence():
    """0.2.1 P0-12：'long black hair' 应命中 'her long black hair'（词边界去重）。"""
    bible = make_bible("A young woman", [
        {"name": "hair", "value": "long black hair", "category": "stable", "locked": True}])
    r = render_anima("Her long black hair flows in the wind.",
                     bible=bible, prompt_mode="natural_language")
    assert r.positive.count("long black hair") == 1


def test_natural_dedup_partial_word_still_kept():
    """0.2.1 P0-12：'hair' 不应命中 'long black hair'（避免过度删除）。"""
    bible = make_bible("A young woman", [
        {"name": "hair", "value": "hair", "category": "stable", "locked": True}])
    r = render_anima("She has long black hair.",
                     bible=bible, prompt_mode="natural_language")
    # "hair" 是 'long black hair' 的子串但非词边界匹配 → 保留追加
    assert "hair" in r.positive


def test_multi_person_spec_scenario_binding():
    """0.2.1 P0-12 §3：A(黑色短发/白色军装) + B(金色长发/黑色礼服)，A 牵 B 手，
    不得产生 A 穿黑裙 / B 穿白色军装。"""
    plan = AnimaPromptPlan(
        characters=[
            AnimaCharacter(character_id="char_01", name="A",
                           required_traits=["short black hair"],
                           variable_traits=["white military uniform"],
                           action="holds B's hand", position="left"),
            AnimaCharacter(character_id="char_02", name="B",
                           required_traits=["long blonde hair"],
                           variable_traits=["black dress"],
                           position="right"),
        ],
        scene_description="")
    r = render_anima_plan(plan, variant="base", prompt_mode="natural_language")
    pos = r.positive
    assert "short black hair" in pos
    assert "white military uniform" in pos
    assert "long blonde hair" in pos
    assert "black dress" in pos
    # 属性不得串位：黑色礼服绝不能出现在 A 的句子里
    a_part, _, b_part = pos.partition("long blonde hair")
    assert "black dress" not in a_part


def test_build_anima_plan_separates_required_and_variable():
    bible = make_bible("少女", [
        {"name": "hair", "value": "black hair", "category": "stable", "locked": True},
        {"name": "dress", "value": "red dress", "category": "variable"},
        {"name": "smile", "value": "smiling", "category": "current"},
    ])
    plan = build_anima_plan("She walks in.", bible)
    c = plan.characters[0]
    assert c.required_traits == ["black hair"]
    assert set(c.variable_traits) == {"red dress", "smiling"}


# ---------------------------------------------------------------- Hybrid 不重复

def test_hybrid_no_duplication_with_llm_plan():
    plan = AnimaPromptPlan(
        control_tags=["1girl", "masterpiece"],
        scene_description="A girl stands by the window.",
        characters=[AnimaCharacter(name="A girl",
                                   required_traits=["long black hair", "blue eyes"])])
    r = render_anima_plan(plan, variant="base", prompt_mode="hybrid")
    # 控制标签块出现一次，正文出现一次，正文绝不再次被当标签追加
    assert r.positive.count("long black hair") == 1
    assert r.positive.count("1girl") == 1
    assert r.positive.count("stands by the window") == 1
    assert r.positive.count(plan.scene_description) == 1


def test_hybrid_input_text_not_reappended_as_tags():
    # 确定性路径：Hybrid 不应把输入正文再当标签重复追加（旧 bug 回归）
    r = render_anima("1girl, long black hair, blue eyes", variant="base",
                     prompt_mode="hybrid")
    assert r.positive.count("long black hair") == 1
    assert r.positive.count("blue eyes") == 1


# ---------------------------------------------------------------- 多人物绑定

def test_multi_character_binding_preserved():
    plan = AnimaPromptPlan(
        characters=[
            AnimaCharacter(character_id="char_01", name="A",
                           required_traits=["short black hair"],
                           variable_traits=["white uniform"],
                           action="holds B's hand",
                           position="left"),
            AnimaCharacter(character_id="char_02", name="B",
                           required_traits=["long blonde hair"],
                           variable_traits=["black evening dress"],
                           position="right"),
        ],
        scene_description="The two stand facing each other.",
        environment=["a dim bar interior"])
    r = render_anima_plan(plan, variant="base", prompt_mode="natural_language")
    pos = r.positive
    # 白色制服属于 A、黑色礼服属于 B，且不互相串位
    assert "short black hair" in pos
    assert "white uniform" in pos
    assert "long blonde hair" in pos
    assert "black evening dress" in pos
    # 黑发/黑裙不能都被绑定到同一句（A 句含白制服，B 句含黑裙）
    a_ok = "white uniform" not in pos.split("long blonde hair")[1]
    assert a_ok


def test_llm_plan_json_parse_multi_character():
    raw = json.dumps({
        "normal_form_version": "2.0",
        "characters": [
            {"character_id": "char_01", "name": "A",
             "required_traits": ["short black hair"],
             "variable_traits": ["white uniform"], "action": "grabbing B's hand",
             "position": "left"},
            {"character_id": "char_02", "name": "B",
             "required_traits": ["long blonde hair"],
             "variable_traits": ["black dress"], "position": "right"},
        ],
        "scene_description": "They face each other in a corridor.",
        "environment": ["school corridor"], "lighting": "soft window light",
        "style": ["anime"],
    })
    plan = parse_anima_plan(raw)
    assert len(plan.characters) == 2
    assert plan.characters[0].character_id == "char_01"
    assert plan.scene_description == "They face each other in a corridor."
    assert plan.environment == ["school corridor"]
    assert plan.lighting == "soft window light"
    r = render_anima_plan(plan, prompt_mode="natural_language")
    assert "white uniform" in r.positive and "black dress" in r.positive
    assert "school corridor." in r.positive
    assert "soft window light." in r.positive


def test_parse_anima_plan_fallback_plain_text():
    plan = parse_anima_plan("A girl walks into a cafe.")
    assert plan.scene_description == "A girl walks into a cafe."
    assert plan.characters == []


def test_parse_anima_plan_fallback_keeps_bible():
    bible = make_bible("少女", [{"name": "hair", "value": "black hair",
                                "category": "stable"}])
    plan = parse_anima_plan("some raw text", bible)
    assert plan.characters and plan.characters[0].required_traits == ["black hair"]


# ---------------------------------------------------------------- Tags 从 Plan

def test_tags_mode_from_plan_control_tags():
    plan = AnimaPromptPlan(control_tags=["score_7", "safe", "masterpiece"],
                           characters=[AnimaCharacter(
                               name="1girl", required_traits=["long_hair"],
                               action="running")],
                           environment=["rainy street"], style=["anime"],
                           artist_tags=["@big chungus"])
    r = render_anima_plan(plan, variant="base", prompt_mode="tags")
    # 0.2.1：Plan 里的 safety 标签不自动注入（只随用户 safety_tag），默认 none
    assert r.positive.startswith("masterpiece, best quality, score_7, ")
    assert "safe" not in r.positive
    assert "long hair" in r.positive  # 下划线规范化
    assert "running" in r.positive
    assert "rainy street" in r.positive
    assert "anime" in r.positive
    assert "@big chungus" in r.positive


def test_tags_mode_user_safety_tag_wins():
    plan = AnimaPromptPlan(control_tags=["score_7", "masterpiece"],
                           supplemental_tags=["1girl"])
    r = render_anima_plan(plan, variant="base", prompt_mode="tags",
                          safety_tag="nsfw")
    assert "nsfw" in r.positive
    assert "safe" not in r.positive


def test_formal_plan_negative_constraints_reach_negative_prompt():
    plan = AnimaPromptPlan(
        scene_description="A portrait.",
        negative_constraints=["blue eyes", "extra fingers"],
    )

    result = render_anima_plan(plan, prompt_mode="natural_language")
    assert "blue eyes" in result.negative
    assert "extra fingers" in result.negative

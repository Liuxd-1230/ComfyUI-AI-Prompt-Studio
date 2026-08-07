"""ANIMA 渲染器 + 校验器测试（规范 §11 ANIMA 用例）。"""
import pytest

from aps.renderers.anima import (
    ANIMA_BASE_NEGATIVE,
    ANIMA_BASE_PREFIX,
    classify,
    order_tags,
    render_anima,
    split_tags,
)
from aps.schemas.character import CharacterBible, CharacterTrait
from aps.schemas.prompt_plan import GenerationProfile
from aps.validators.anima import validate_anima


def test_base_uses_official_prefix_and_negative():
    r = render_anima("1girl, long hair, @artist x, red dress",
                     variant="base", prompt_mode="tags")
    assert r.positive.startswith(ANIMA_BASE_PREFIX)
    assert r.negative == ANIMA_BASE_NEGATIVE
    assert "score_7" in r.positive
    assert "score_1" in r.negative


def test_aesthetic_no_score():
    r = render_anima("1girl, sunset", variant="aesthetic")
    assert "score_" not in r.positive
    assert "score_" not in r.negative
    assert r.profile.cfg == 4.5


def test_turbo_profile():
    r = render_anima("1girl", variant="turbo")
    assert r.profile.cfg == 1.0
    assert r.profile.steps == 10
    assert "score_" not in r.positive


def test_sensitive_tier():
    r = render_anima("1girl", variant="base", safety_tag="sensitive")
    assert "sensitive" in r.positive
    assert "safe" not in r.positive


def test_safety_none_injects_nothing():
    r = render_anima("1girl, long hair", variant="base", prompt_mode="tags")
    assert "safe" not in r.positive
    assert "sensitive" not in r.positive
    assert "nsfw" not in r.positive
    assert "explicit" not in r.positive
    assert r.positive.startswith(ANIMA_BASE_PREFIX)  # 前缀不再包含安全标签


def test_safety_tags_explicit_all_variants():
    for tag in ("safe", "sensitive", "nsfw", "explicit"):
        r = render_anima("1girl", variant="base", prompt_mode="tags",
                         safety_tag=tag)
        assert tag in r.positive
        assert r.positive.startswith(ANIMA_BASE_PREFIX)


def test_safety_natural_and_hybrid_modes():
    for mode in ("natural_language", "hybrid"):
        r = render_anima("A girl standing in a garden", variant="base",
                         prompt_mode=mode, safety_tag="safe")
        assert "safe" in r.positive
        r2 = render_anima("A girl standing in a garden", variant="base",
                          prompt_mode=mode, safety_tag="none")
        assert "safe" not in r2.positive


def test_safety_tag_invalid_falls_back_none():
    r = render_anima("1girl", variant="base", prompt_mode="tags",
                     safety_tag="whatever")
    assert "whatever" not in r.positive
    assert "safe" not in r.positive


def test_artist_tag_ordered_before_general():
    tags = order_tags(["running", "@big chungus", "1girl", "safe", "masterpiece"])
    assert tags.index("@big chungus") < tags.index("running")
    assert tags.index("1girl") < tags.index("@big chungus")


def test_underscore_normalization():
    r = render_anima("long_hair, red_dress, score_7", variant="base",
                     prompt_mode="tags")
    assert "long hair" in r.positive
    assert "red dress" in r.positive
    assert "long_hair" not in r.positive
    assert any("下划线" in w for w in r.warnings)


def test_dedupe_bible_and_input():
    bible = CharacterBible(name="少女")
    bible.traits.append(CharacterTrait(name="hair", value="long dark hair",
                                       category="stable"))
    r = render_anima("long dark hair, 1girl", variant="base", bible=bible,
                     prompt_mode="tags")
    assert r.positive.count("long dark hair") == 1


def test_lora_triggers_appended():
    r = render_anima("1girl", variant="base", lora_triggers=["my_lora_trigger", "x"])
    assert r.positive.rstrip().endswith("my_lora_trigger, x") or \
        ", my_lora_trigger" in r.positive


def test_natural_language_mode_keeps_text():
    r = render_anima("A girl with long hair walks under the rain.",
                     variant="base", prompt_mode="natural_language")
    assert r.positive.startswith("masterpiece")
    assert "A girl with long hair" in r.positive


def test_unknown_variant_raises():
    with pytest.raises(ValueError):
        render_anima("x", variant="bogus")


def test_split_tags():
    assert split_tags(" 1girl , 1girl, LONG hair ,, ") == ["1girl", "long hair"]
    assert split_tags("") == []


def test_classify():
    assert classify("score_7") == "quality"
    assert classify("masterpiece") == "quality"
    assert classify("safe") == "safety"
    assert classify("1girl") == "count"
    assert classify("@artist") == "artist"
    assert classify("year 2025") == "meta_year"
    assert classify("anything") == "general"


# ------------------------------------------------------------------ validator

def test_validator_empty_positive_error():
    report = validate_anima("", variant="base")
    assert report.valid is False
    assert any(i.code == "anima_empty_positive" for i in report.issues)


def test_validator_aesthetic_score_warns():
    report = validate_anima("masterpiece, best quality, safe, score_7, 1girl",
                            variant="aesthetic")
    assert any(i.code == "anima_no_score" for i in report.issues)


def test_validator_underscore_and_uppercase():
    report = validate_anima("masterpiece, best quality, score_7, safe, Long_Hair, 1girl",
                            variant="base")
    codes = {i.code for i in report.issues}
    assert "anima_underscore" in codes
    assert "anima_uppercase" in codes


def test_validator_duplicate():
    report = validate_anima("masterpiece, best quality, score_7, safe, 1girl, 1girl",
                            variant="base")
    assert any(i.code == "anima_duplicate" for i in report.issues)


def test_validator_negative_core():
    report = validate_anima("masterpiece, best quality, score_7, safe, 1girl",
                            negative="bad quality", variant="base")
    assert any(i.code == "anima_negative_core" for i in report.issues)


def test_validator_base_ok():
    report = validate_anima("masterpiece, best quality, score_7, safe, 1girl, @artist x",
                            negative=ANIMA_BASE_NEGATIVE, variant="base")
    assert report.valid is True


def test_validator_natural_language_skips_tag_rules():
    report = validate_anima("A girl walks into a cafe.", variant="base",
                            prompt_mode="natural_language")
    assert report.valid is True

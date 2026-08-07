"""节点层测试：Reference Analyzer（文字/多图共识/透传）与 Character Bible（合并/锁定）。"""
import json

import numpy as np
import pytest

import aps.nodes.reference_analyzer as ra_mod
import aps.nodes.character_bible as cb_mod
from aps.schemas.character import CharacterBible, CharacterBook, CharacterCandidate
from aps.schemas.references import ReferenceManifest
from aps.schemas.results import LLMResult


def setup_profile(store):
    store.create_profile({"profile_id": "p1", "name": "DeepSeek",
                          "vision_base_url": "http://v:8000/v1",
                          "vision_model": "qwen-vl-max"})
    store.set_api_key("p1", "sk-abcdef1234567890")
    return store.get_profile("p1").node_payload()


def anchor_json(name="少女", value="红发", category="stable"):
    return json.dumps({"name": name, "traits": [
        {"name": "hair", "value": value, "category": category, "confidence": 0.9}]})


# ------------------------------------------------------------------ Analyzer

def test_analyzer_text_only(monkeypatch, store):
    payload = setup_profile(store)

    class FakeGateway:
        def generate(self, profile, api_key, req):
            return LLMResult(text=anchor_json())

    monkeypatch.setattr(ra_mod, "Gateway", lambda: FakeGateway())
    node = ra_mod.APS_ReferenceAnalyzer()
    analysis, candidate, manifest, caption, conf, raw, images = node.analyze(
        AI_PROFILE=payload, analysis_mode="character_full",
        text_anchor="红发少女", images=None, character_bible=None, custom_prompt="")
    cand = CharacterCandidate.from_json(candidate)
    assert cand.name == "少女"
    assert cand.traits[0].value == "红发"
    assert "text_anchor" in cand.sources[0]
    assert images is None  # 无输入透传 None
    manf = ReferenceManifest.from_json(manifest)
    assert manf.assets == []


def test_analyzer_images_consensus_and_passthrough(monkeypatch, store):
    payload = setup_profile(store)
    responses = iter([
        anchor_json(value="黑发", category="stable"),
        anchor_json(value="金发", category="stable"),
    ])
    monkeypatch.setattr(ra_mod.vision_svc, "call_vision",
                        lambda *a, **k: {"ok": True, "text": next(responses),
                                         "raw": "raw"})
    node = ra_mod.APS_ReferenceAnalyzer()
    imgs = [np.random.rand(16, 16, 3).astype(np.float32),
            np.random.rand(16, 16, 3).astype(np.float32)]
    out = node.analyze(AI_PROFILE=payload, analysis_mode="character_full",
                       text_anchor="", images=imgs, character_bible=None,
                       custom_prompt="")
    analysis, candidate, manifest, caption, conf, raw, images = out
    cand = CharacterCandidate.from_json(candidate)
    # 两图值冲突 → consensus 标记 uncertain
    assert cand.traits[0].category == "uncertain"
    assert images is imgs  # IMAGE 原样透传（同对象）
    manf = ReferenceManifest.from_json(manifest)
    assert len(manf.assets) == 2
    assert len(manf.subjects) == 1


def test_analyzer_text_priority_over_images(monkeypatch, store):
    payload = setup_profile(store)

    class FakeGateway:
        def generate(self, profile, api_key, req):
            return LLMResult(text=anchor_json(value="黑发"))

    monkeypatch.setattr(ra_mod, "Gateway", lambda: FakeGateway())
    monkeypatch.setattr(ra_mod.vision_svc, "call_vision",
                        lambda *a, **k: {"ok": True, "text": anchor_json(value="金发"),
                                         "raw": "r"})
    node = ra_mod.APS_ReferenceAnalyzer()
    _, candidate, _, _, _, _, _ = node.analyze(
        AI_PROFILE=payload, analysis_mode="character_full",
        text_anchor="黑发", images=[np.random.rand(8, 8, 3).astype(np.float32)],
        character_bible=None, custom_prompt="")
    cand = CharacterCandidate.from_json(candidate)
    assert cand.traits[0].value == "黑发"  # 文字优先


def test_analyzer_no_inputs_warns(monkeypatch, store):
    payload = setup_profile(store)
    node = ra_mod.APS_ReferenceAnalyzer()
    analysis, candidate, manifest, caption, conf, raw, images = node.analyze(
        AI_PROFILE=payload, analysis_mode="character_full",
        text_anchor="", images=None, character_bible=None, custom_prompt="")
    anl = analysis if isinstance(analysis, dict) else json.loads(analysis)
    assert any("没有文字锚点" in w for w in anl["warnings"])


def test_analyzer_vision_error_readable(monkeypatch, store):
    payload = setup_profile(store)
    from aps.schemas.results import make_error

    monkeypatch.setattr(ra_mod.vision_svc, "call_vision",
                        lambda *a, **k: {"ok": False,
                                         "error": make_error("network_error", "无法连接")})
    node = ra_mod.APS_ReferenceAnalyzer()
    with pytest.raises(ValueError, match="无法连接"):
        node.analyze(AI_PROFILE=payload, analysis_mode="character_full",
                     text_anchor="", images=[np.zeros((4, 4, 3))],
                     character_bible=None, custom_prompt="")


def test_analyzer_custom_mode_requires_prompt(store):
    payload = setup_profile(store)
    node = ra_mod.APS_ReferenceAnalyzer()
    with pytest.raises(ValueError, match="custom_prompt"):
        node.analyze(AI_PROFILE=payload, analysis_mode="custom",
                     text_anchor="", images=None, character_bible=None,
                     custom_prompt="")


# ------------------------------------------------------------------ Bible

def test_bible_merge_with_lock(store):
    node = cb_mod.APS_CharacterBible()
    existing = CharacterBible(name="少女")
    existing.traits.append(__trait("hair", "black", sources=["text_anchor"]))
    _, prompt, json_out, conflicts, uncertainty, book_json, warnings = node.merge(
        merge_strategy="image_priority",
        character_candidate=CharacterCandidate(
            traits=[__trait("hair", "blonde", sources=["image:0"])]).to_json(),
        existing_bible=existing.to_json(), text_anchor="蓝裙子",
        lock_fields="hair", character_name="少女")
    bible = CharacterBible.from_json(json.loads(json_out))
    assert bible.name == "少女"
    assert "hair" in bible.locked_fields
    # 锁定字段不被 image_priority 覆盖
    assert bible.trait_map()["hair"].value == "black"
    assert any(t.value == "蓝裙子" for t in bible.traits)  # 锚点片段追加
    assert "hair" in conflicts  # 锁定字段与候选冲突被记录
    book = CharacterBook.from_json(book_json)
    assert len(book.characters) == 1


def test_bible_text_priority(store):
    node = cb_mod.APS_CharacterBible()
    candidate = CharacterCandidate(traits=[__trait("hair", "blonde", sources=["image:0"])])
    existing = CharacterBible(name="t")
    existing.traits.append(__trait("hair", "black", sources=["text_anchor"]))
    _, prompt, json_out, conflicts, _, book_json, _ = node.merge(
        merge_strategy="text_priority",
        character_candidate=candidate.to_json(),
        existing_bible=existing.to_json(), text_anchor="", lock_fields="",
        character_name="")
    bible = CharacterBible.from_json(json.loads(json_out))
    assert bible.traits[0].value == "black"  # 文字锚点来源优先


def test_bible_speaker_id_auto():
    # 独立 CharacterBible 不默认 S1（避免多人物撞号）；唯一 ID 由 CharacterBook 分配
    b = CharacterBible(character_id="c1")
    assert b.speaker_id == ""
    b2 = CharacterBible(character_id="c2", speaker_id="S2")
    assert b2.speaker_id == "S2"


def __trait(name, value, sources=None):
    from aps.schemas.character import CharacterTrait

    return CharacterTrait(name=name, value=value, sources=list(sources or []))

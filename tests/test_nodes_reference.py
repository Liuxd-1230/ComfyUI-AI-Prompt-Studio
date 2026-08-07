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
    # 响应顺序：逐图分析（2 张）→ VLM 整体身份判断（0.2.1 P0-14：一次多图判断）
    responses = iter([
        anchor_json(value="黑发", category="stable"),
        anchor_json(value="金发", category="stable"),
        '{"same_subject": false, "confidence": 0.1, '
        '"evidence": ["different hair colors"], "reasons_if_different": []}',
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
    # 两图 stable 特征值冲突 → 身份判断为不同主体：不跨主体串绑特征，
    # 只取最高一致度分组；身份冲突以 warning + __subject_identity__ conflict 记录
    assert cand.same_subject is False
    assert any(c.trait_name == "__subject_identity__" for c in cand.conflicts)
    assert cand.traits[0].category == "stable"      # 未混合成 uncertain
    anl = analysis if isinstance(analysis, dict) else json.loads(analysis)
    assert any("不同主体" in w for w in anl["warnings"])
    assert images is imgs  # IMAGE 原样透传（同对象）
    manf = ReferenceManifest.from_json(manifest)
    assert len(manf.assets) == 2
    assert len(manf.subjects) == 1


def test_analyzer_vlm_identity_fallback_on_failure(monkeypatch, store):
    """VLM 身份判断失败 → 回退 deterministic heuristic（0.2.1 P0-14）。"""
    payload = setup_profile(store)
    responses = iter([
        anchor_json(value="黑发", category="stable"),
        anchor_json(value="金发", category="stable"),
        {"ok": False, "error": "视觉端点错误"},   # 身份判断调用失败
    ])

    def fake_vision(*a, **k):
        resp = next(responses)
        if isinstance(resp, dict) and resp.get("ok") is False:
            return resp
        return {"ok": True, "text": resp, "raw": "raw"}

    monkeypatch.setattr(ra_mod.vision_svc, "call_vision", fake_vision)
    node = ra_mod.APS_ReferenceAnalyzer()
    imgs = [np.random.rand(16, 16, 3).astype(np.float32),
            np.random.rand(16, 16, 3).astype(np.float32)]
    analysis, candidate, _, _, _, raw, _ = node.analyze(
        AI_PROFILE=payload, analysis_mode="character_full",
        text_anchor="", images=imgs, character_bible=None, custom_prompt="")
    cand = CharacterCandidate.from_json(candidate)
    anl = analysis if isinstance(analysis, dict) else json.loads(analysis)
    # 回退 heuristic：冲突 → 不同主体，仍防串绑
    assert cand.same_subject is False
    assert any("回退" in w for w in anl["warnings"])


def test_analyzer_vlm_same_subject_authoritative(monkeypatch, store):
    """0.2.1a：VLM 判断同一主体（conf 0.95）→ 即使 stable 字符串不一致
    （'black short hair' vs 'short black hair'）也合并为同一个人物。"""
    payload = setup_profile(store)
    responses = iter([
        json.dumps({"name": "A", "traits": [
            {"name": "hair", "value": "black short hair", "category": "stable",
             "confidence": 0.9}]}),
        json.dumps({"name": "A", "traits": [
            {"name": "hair", "value": "short black hair", "category": "stable",
             "confidence": 0.9}]}),
        '{"same_subject": true, "confidence": 0.95, '
        '"evidence": ["same face proportions", "same hairline"], "reasons_if_different": []}',
    ])
    monkeypatch.setattr(ra_mod.vision_svc, "call_vision",
                        lambda *a, **k: {"ok": True, "text": next(responses),
                                         "raw": "raw"})
    node = ra_mod.APS_ReferenceAnalyzer()
    imgs = [np.random.rand(16, 16, 3).astype(np.float32),
            np.random.rand(16, 16, 3).astype(np.float32)]
    analysis, candidate, _, _, _, _, _ = node.analyze(
        AI_PROFILE=payload, analysis_mode="character_full",
        text_anchor="", images=imgs, character_bible=None, custom_prompt="")
    cand = CharacterCandidate.from_json(candidate)
    anl = analysis if isinstance(analysis, dict) else json.loads(analysis)
    # VLM same=true：同一个人物，identity_confidence 取 VLM 的 0.95
    assert cand.same_subject is True
    assert cand.identity_confidence == 0.95
    assert any("指向同一主体" in w for w in anl["warnings"])
    # 字符串不一致不再是「不同主体」的证据（VLM 权威）
    assert not any("不同主体" in w for w in anl["warnings"])


def test_analyzer_vlm_different_subject_blocks_merge(monkeypatch, store):
    """0.2.1a：VLM 判断不同主体 → 即使 stable 字符串碰巧一致也不合并
    （VLM 结论优先，旧字符串算法不再覆盖）。"""
    payload = setup_profile(store)
    responses = iter([
        json.dumps({"name": "X", "traits": [
            {"name": "hair", "value": "long dark hair", "category": "stable",
             "confidence": 0.9},
            {"name": "face", "value": "round face", "category": "stable",
             "confidence": 0.9}]}),
        json.dumps({"name": "Y", "traits": [
            {"name": "hair", "value": "long dark hair", "category": "stable",
             "confidence": 0.9},
            {"name": "face", "value": "round face", "category": "stable",
             "confidence": 0.9}]}),
        '{"same_subject": false, "confidence": 0.1, '
        '"evidence": ["different facial structure"], "reasons_if_different": ["different bone structure"]}',
    ])
    monkeypatch.setattr(ra_mod.vision_svc, "call_vision",
                        lambda *a, **k: {"ok": True, "text": next(responses),
                                         "raw": "raw"})
    node = ra_mod.APS_ReferenceAnalyzer()
    imgs = [np.random.rand(16, 16, 3).astype(np.float32),
            np.random.rand(16, 16, 3).astype(np.float32)]
    analysis, candidate, _, _, _, _, _ = node.analyze(
        AI_PROFILE=payload, analysis_mode="character_full",
        text_anchor="", images=imgs, character_bible=None, custom_prompt="")
    cand = CharacterCandidate.from_json(candidate)
    anl = analysis if isinstance(analysis, dict) else json.loads(analysis)
    # VLM same=false：不合并为同一人物（字符串一致不再覆盖 VLM）
    assert cand.same_subject is False
    assert any(w.startswith("特征冲突 __subject_identity__") for w in anl["warnings"])
    assert any("不同主体" in w for w in anl["warnings"])


def test_analyzer_vlm_different_subject_single_cluster_vetoes_merge(monkeypatch, store):
    """0.2.1b：VLM 判定不同主体，但 stable 字符串一致度恰好把候选聚成一组时，
    **必须真正否决全量合并**——只取置信度最高的一张作为主人物，其余保留为
    身份冲突（不再把两个人的 traits 合进同一个 candidate）。"""
    payload = setup_profile(store)
    responses = iter([
        json.dumps({"name": "X", "traits": [
            {"name": "hair", "value": "long dark hair", "category": "stable",
             "confidence": 0.95},
            {"name": "face", "value": "round face", "category": "stable",
             "confidence": 0.95}]}),
        json.dumps({"name": "Y", "traits": [
            {"name": "hair", "value": "long dark hair", "category": "stable",
             "confidence": 0.5},
            {"name": "face", "value": "round face", "category": "stable",
             "confidence": 0.5}]}),
        '{"same_subject": false, "confidence": 0.1, "evidence": [], "reasons_if_different": []}',
    ])
    monkeypatch.setattr(ra_mod.vision_svc, "call_vision",
                        lambda *a, **k: {"ok": True, "text": next(responses),
                                         "raw": "raw"})
    node = ra_mod.APS_ReferenceAnalyzer()
    imgs = [np.random.rand(16, 16, 3).astype(np.float32),
            np.random.rand(16, 16, 3).astype(np.float32)]
    analysis, candidate, _, _, _, _, _ = node.analyze(
        AI_PROFILE=payload, analysis_mode="character_full",
        text_anchor="", images=imgs, character_bible=None, custom_prompt="")
    cand = CharacterCandidate.from_json(candidate)
    anl = analysis if isinstance(analysis, dict) else json.loads(analysis)
    assert cand.same_subject is False
    # 未全量合并：主人物只来自一张图（sources 只有 image:0 或 image:1 一个来源）
    img_sources = [s for s in cand.sources if s.startswith("image:")]
    assert len(img_sources) == 1, f"期望只取一张图作为主人物，实际来源: {img_sources}"
    # 其余图保留为身份冲突，警告明确说明「未合并」
    assert any(w.startswith("特征冲突 __subject_identity__") for w in anl["warnings"])
    assert any("未合并" in w for w in anl["warnings"])


def test_analyzer_images_only_without_text_api_key(monkeypatch, store):
    """0.2.1b：只做图片分析时，文本档案无 API Key 也可运行（密钥来自视觉档案）。"""
    store.create_profile({"profile_id": "textprof", "name": "Text",
                          "vision_profile_id": "visprof"})   # 无 API Key
    store.create_profile({"profile_id": "visprof", "name": "Vision",
                          "vision_base_url": "http://v:8000/v1",
                          "vision_model": "qwen-vl-max"})
    store.set_api_key("visprof", "sk-vis-123")
    payload = store.get_profile("textprof").node_payload()
    responses = iter([
        json.dumps({"name": "A", "traits": [
            {"name": "hair", "value": "red hair", "category": "stable",
             "confidence": 0.9}]}),
    ])
    monkeypatch.setattr(ra_mod.vision_svc, "call_vision",
                        lambda *a, **k: {"ok": True, "text": next(responses),
                                         "raw": "raw"})
    node = ra_mod.APS_ReferenceAnalyzer()
    analysis, candidate, _, _, _, _, _ = node.analyze(
        AI_PROFILE=payload, analysis_mode="character_full",
        text_anchor="", images=[np.random.rand(8, 8, 3).astype(np.float32)],
        character_bible=None, custom_prompt="")
    cand = CharacterCandidate.from_json(candidate)
    assert cand.traits[0].value == "red hair"   # 未因文本档案无 Key 报错


def test_analyzer_text_anchor_requires_text_key(monkeypatch, store):
    """0.2.1b：有 text_anchor 时必须要求文本档案的 API Key（仍不因 Key 缺失而绕过）。"""
    store.create_profile({"profile_id": "nokey", "name": "NoKey"})   # 无 Key
    payload = store.get_profile("nokey").node_payload()
    node = ra_mod.APS_ReferenceAnalyzer()
    with pytest.raises(ValueError, match="API Key"):
        node.analyze(AI_PROFILE=payload, analysis_mode="character_full",
                     text_anchor="红发少女", images=None,
                     character_bible=None, custom_prompt="")


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

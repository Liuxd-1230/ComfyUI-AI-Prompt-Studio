"""参考分析核心逻辑测试：解析 / 共识 / 合并策略 / Manifest。"""
from aps.schemas.character import (
    CharacterBible,
    CharacterCandidate,
    CharacterConflict,
    CharacterTrait,
)
from aps.schemas.references import AssetRef
from aps.services import reference


# ------------------------------------------------------------------ 解析

def test_parse_anchor_fragments():
    traits = reference.parse_anchor_fragments("红发少女，蓝裙子；白色衬衫")
    assert len(traits) == 3
    assert all(t.category == "stable" for t in traits)
    assert all("text_anchor" in t.sources for t in traits)
    assert reference.parse_anchor_fragments("  ") == []


def test_extract_json_object():
    assert reference.extract_json_object('{"a": 1}') == {"a": 1}
    assert reference.extract_json_object('```json\n{"b": 2}\n```') == {"b": 2}
    assert reference.extract_json_object('前言 {"c": 3} 后记') == {"c": 3}
    assert reference.extract_json_object("不是 JSON") is None


def test_parse_candidate_json():
    raw = ('{"name": "少女", "traits": ['
           '{"name": "hair_color", "value": "long dark brown hair", "category": "stable", "confidence": 0.9},'
           '{"name": "mood", "value": "happy", "category": "bogus", "confidence": 99},'
           '{"name": "x", "value": "", "confidence": 0.5}]}')
    cand = reference.parse_candidate_json(raw, "character_full", ["image:0"])
    assert cand.name == "少女"
    assert cand.traits[0].value == "long dark brown hair"
    assert cand.traits[0].category == "stable"
    assert cand.traits[1].category == "uncertain"  # 非法类别不得升级为确定事实
    assert cand.traits[1].confidence == 1.0     # 置信度钳制到 [0,1]
    assert len(cand.traits) == 2                 # 空 value 丢弃
    assert "image:0" in cand.traits[0].sources


def test_parse_candidate_json_invalid():
    cand = reference.parse_candidate_json("模型没有返回 JSON", "character_full")
    assert cand.traits == []
    assert cand.confidence == 0.0


# ------------------------------------------------------------------ 共识

def test_consensus_agreement():
    c1 = CharacterCandidate(traits=[CharacterTrait(name="hair", value="black", confidence=0.8)])
    c2 = CharacterCandidate(traits=[CharacterTrait(name="hair", value="black", confidence=0.9)])
    merged = reference.consensus_of([c1, c2])
    assert len(merged.traits) == 1
    assert merged.traits[0].value == "black"
    assert merged.traits[0].category == "stable"


def test_consensus_conflict_marks_uncertain():
    c1 = CharacterCandidate(traits=[CharacterTrait(name="hair", value="black", confidence=0.9)])
    c2 = CharacterCandidate(traits=[CharacterTrait(name="hair", value="blonde", confidence=0.8)])
    merged = reference.consensus_of([c1, c2])
    assert merged.traits[0].value == "black"     # 置信度最高者
    assert merged.traits[0].category == "uncertain"


# ------------------------------------------------------------------ 多图身份判断

def _trait(name, value, category="stable"):
    return CharacterTrait(name=name, value=value, category=category)


def test_identity_agreement_shared_stable():
    a = CharacterCandidate(traits=[_trait("hair", "black"), _trait("eyes", "brown")])
    b = CharacterCandidate(traits=[_trait("hair", "black"), _trait("eyes", "blue")])
    assert reference.identity_agreement(a, b) == 0.5


def test_identity_agreement_no_shared_stable_zero():
    a = CharacterCandidate(traits=[_trait("hair", "black", "variable")])
    b = CharacterCandidate(traits=[_trait("hair", "blonde", "variable")])
    # 只有 variable 特征：不算身份证据
    assert reference.identity_agreement(a, b) == 0.0


def test_cluster_by_identity_separates_subjects():
    a = CharacterCandidate(traits=[_trait("hair", "black"), _trait("eyes", "brown")])
    b = CharacterCandidate(traits=[_trait("hair", "black"), _trait("eyes", "brown")])
    c = CharacterCandidate(traits=[_trait("hair", "blonde"), _trait("eyes", "blue")])
    clusters = reference.cluster_by_identity([a, b, c])
    assert len(clusters) == 2
    assert len(clusters[0]) + len(clusters[1]) == 3


def test_judge_identity_single_true():
    v = reference.judge_identity([CharacterCandidate()])
    assert v["same_subject"] is True and v["clusters"] == 1


def test_judge_identity_multiple_subjects_false():
    a = CharacterCandidate(traits=[_trait("hair", "black"), _trait("eyes", "brown")])
    c = CharacterCandidate(traits=[_trait("hair", "blonde"), _trait("eyes", "blue")])
    v = reference.judge_identity([a, c])
    assert v["same_subject"] is False
    assert v["clusters"] == 2


def test_identity_consensus_merges_same_subject_only():
    """多主体：只合并最高一致度分组，其余图不串绑进同一个人物。"""
    a = CharacterCandidate(traits=[_trait("hair", "black"), _trait("eyes", "brown")],
                           sources=["image:0"])
    b = CharacterCandidate(traits=[_trait("hair", "black"), _trait("eyes", "brown")],
                           sources=["image:1"])
    c = CharacterCandidate(traits=[_trait("hair", "blonde"), _trait("eyes", "blue")],
                           sources=["image:2"])
    merged = reference.identity_consensus([a, b, c])
    assert merged.same_subject is False
    assert merged.identity_confidence == 0.0
    assert any(c.trait_name == "__subject_identity__" for c in merged.conflicts)
    # 不把不同主体的特征混入
    hair = [t for t in merged.traits if t.name == "hair"]
    assert hair and hair[0].value == "black"


def test_identity_consensus_all_same_subject():
    a = CharacterCandidate(traits=[_trait("hair", "black"), _trait("eyes", "brown")])
    b = CharacterCandidate(traits=[_trait("hair", "black"), _trait("eyes", "brown")])
    merged = reference.identity_consensus([a, b])
    assert merged.same_subject is True
    assert merged.identity_confidence > 0
    assert not [c for c in merged.conflicts if c.trait_name == "__subject_identity__"]


# ------------------------------------------------------------------ 合并策略

def _bible_with(traits, locked=None):
    b = CharacterBible(name="t")
    b.traits = list(traits)
    b.locked_fields = list(locked or [])
    return b


def test_locked_never_overwritten():
    b = _bible_with([CharacterTrait(name="hair", value="black", locked=True)])
    cand = CharacterCandidate(traits=[CharacterTrait(name="hair", value="blonde")])
    reference.merge_candidate_into_bible(b, cand, "image_priority")
    assert b.traits[0].value == "black"
    assert len(b.conflicts) == 1


def test_text_priority_wins():
    b = _bible_with([CharacterTrait(name="hair", value="blonde", sources=["image:0"])])
    cand = CharacterCandidate(traits=[CharacterTrait(name="hair", value="black",
                                                     sources=["text_anchor"])])
    reference.merge_candidate_into_bible(b, cand, "text_priority")
    assert b.traits[0].value == "black"


def test_image_priority_wins():
    b = _bible_with([CharacterTrait(name="hair", value="blonde", sources=["text_anchor"])])
    cand = CharacterCandidate(traits=[CharacterTrait(name="hair", value="black",
                                                     sources=["image:0"])])
    reference.merge_candidate_into_bible(b, cand, "image_priority")
    assert b.traits[0].value == "black"


def test_consensus_higher_confidence_replaces():
    b = _bible_with([CharacterTrait(name="hair", value="black", confidence=0.5)])
    cand = CharacterCandidate(traits=[CharacterTrait(name="hair", value="blonde", confidence=0.95)])
    reference.merge_candidate_into_bible(b, cand, "consensus")
    assert b.traits[0].value == "blonde"


def test_consensus_tie_marks_uncertain():
    b = _bible_with([CharacterTrait(name="hair", value="black", confidence=0.9)])
    cand = CharacterCandidate(traits=[CharacterTrait(name="hair", value="blonde", confidence=0.9)])
    reference.merge_candidate_into_bible(b, cand, "consensus")
    assert b.traits[0].category == "uncertain"
    assert len(b.conflicts) == 1


def test_fill_missing_only_never_overwrites():
    b = _bible_with([CharacterTrait(name="hair", value="black")])
    cand = CharacterCandidate(traits=[CharacterTrait(name="hair", value="blonde"),
                                      CharacterTrait(name="eyes", value="green")])
    reference.merge_candidate_into_bible(b, cand, "fill_missing_only")
    assert b.traits[0].value == "black"
    assert any(t.name == "eyes" for t in b.traits)  # 缺失特征被补上
    assert len(b.conflicts) == 1


def test_manual_priority_keeps_existing():
    b = _bible_with([CharacterTrait(name="hair", value="black")])
    cand = CharacterCandidate(traits=[CharacterTrait(name="hair", value="blonde")])
    reference.merge_candidate_into_bible(b, cand, "manual_priority")
    assert b.traits[0].value == "black"
    assert len(b.conflicts) == 1


def test_same_value_merges_sources_and_confidence():
    b = _bible_with([CharacterTrait(name="hair", value="black", confidence=0.5)])
    cand = CharacterCandidate(traits=[CharacterTrait(name="hair", value="black",
                                                     confidence=0.8, sources=["image:1"])])
    reference.merge_candidate_into_bible(b, cand, "consensus")
    assert b.traits[0].confidence == 0.8
    assert "image:1" in b.traits[0].sources
    assert b.conflicts == []


def test_low_confidence_note():
    b = CharacterBible(name="t")
    cand = CharacterCandidate(confidence=0.2)
    reference.merge_candidate_into_bible(b, cand, "consensus")
    assert b.uncertainty_notes


# ------------------------------------------------------------------ Manifest

def test_build_manifest():
    assets = [AssetRef(asset_id="img_0", asset_type="image", source="input:0"),
              AssetRef(asset_id="img_1", asset_type="image", source="input:1")]
    cand = CharacterCandidate(name="少女", traits=[CharacterTrait(name="hair", value="black")])
    m = reference.build_manifest(assets, [cand], notes="n")
    assert len(m.assets) == 2
    assert len(m.subjects) == 1
    assert m.subjects[0].kind == "character"
    assert m.character_sources[m.subjects[0].subject_id] == ["img_0", "img_1"]


def test_build_manifest_only_binds_candidate_source_images():
    assets = [AssetRef(asset_id="img_0", asset_type="image", source="input:0"),
              AssetRef(asset_id="img_1", asset_type="image", source="input:1")]
    candidate = CharacterCandidate(name="A", sources=["image:1"])
    manifest = reference.build_manifest(assets, [candidate])
    subject = manifest.subjects[0]
    assert subject.source_assets == ["img_1"]
    assert manifest.character_sources[subject.subject_id] == ["img_1"]
    assert assets[0].subject_ids == []
    assert assets[1].subject_ids == [subject.subject_id]

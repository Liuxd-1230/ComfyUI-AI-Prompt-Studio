"""Schema 层测试：往返序列化 / 容错 / 迁移 / 嵌套转换 / 校验。"""
import dataclasses

import pytest

import aps.schemas as S


def test_llm_result_roundtrip():
    r = S.LLMResult(text="hello", reasoning="think", profile_id="p1")
    r.citations.append(S.Citation(index=0, url="https://a.b", title="A"))
    r.tool_calls.append(S.ToolCall(name="web_search", arguments="{}"))
    r.usage = S.Usage(input_tokens=10, output_tokens=5)
    r2 = S.LLMResult.from_json(r.to_json())
    assert r2.text == "hello"
    assert isinstance(r2.citations[0], S.Citation) and r2.citations[0].title == "A"
    assert isinstance(r2.tool_calls[0], S.ToolCall)
    assert isinstance(r2.usage, S.Usage) and r2.usage.input_tokens == 10


@pytest.mark.parametrize("cls", [
    S.AIProfile, S.LLMResult, S.ChatSession, S.ReferenceAnalysis,
    S.CharacterCandidate, S.ReferenceManifest, S.CharacterBible, S.Storyboard,
    S.StoryItem, S.StoryItemList, S.PromptPlan, S.GenerationProfile, S.H3PromptPlan,
])
def test_all_core_types_roundtrip(cls):
    obj = cls.from_json({})
    assert isinstance(obj, cls)
    assert obj.schema_version == S.SCHEMA_VERSION
    assert cls.from_json(obj.to_json()) == obj


def test_tolerant_input():
    dirty = {"text": 123, "unknown_key": True, "warnings": ["x", "y"]}
    r = S.LLMResult.from_json(dirty)
    assert r.text == "123"          # 类型收敛
    assert r.warnings == ["x", "y"]  # 已知键保留
    assert r.reasoning == ""         # 缺失取默认


def test_migration():
    @dataclasses.dataclass
    class M(S.Schema):
        a: str = ""
        b: int = 0

    M.MIGRATIONS = {"0.9": {"1.0": lambda d: {**d, "b": int(d.get("b") or 0) + 1}}}
    m = M.from_json({"schema_version": "0.9", "a": "x", "b": 1})
    assert m.b == 2
    assert m.schema_version == S.SCHEMA_VERSION


def test_bad_migration_raises():
    @dataclasses.dataclass
    class M(S.Schema):
        a: str = ""

    M.MIGRATIONS = {"0.9": {"1.0": lambda d: (_ for _ in ()).throw(ValueError("boom"))}}
    with pytest.raises(S.SchemaError):
        M.from_json({"schema_version": "0.9", "a": "x"})


def test_profile_node_payload_has_no_key_ref():
    p = S.AIProfile(profile_id="d1", api_key_ref="sk-secret")
    payload = p.node_payload()
    assert "api_key_ref" not in payload
    assert "profile_id" in payload


def test_profile_validate():
    assert S.AIProfile(profile_id="d1").validate() == []
    bad = S.AIProfile(profile_id="", protocol="bogus", reasoning="x",
                      web_search="y", unload_policy="z", base_url="")
    assert len(bad.validate()) >= 5


def test_type_registry():
    assert S.schema_class_for(S.H3_PROMPT_PLAN) is S.H3PromptPlan
    assert S.schema_class_for(S.AI_PROFILE) is S.AIProfile
    assert S.schema_class_for("NOPE") is None


def test_chat_session():
    sess = S.ChatSession(profile_id="p1")
    sess.append(S.ChatMessage(role="user", content="hi"))
    assert len(sess.messages) == 1
    assert sess.id.startswith("sess_")
    restored = S.ChatSession.from_json(sess.to_json())
    assert restored.messages[0].content == "hi"


def test_storyboard_character_ids(storyboard):
    assert storyboard.all_character_ids() == ["c1", "c2"]


def test_storyboard_select_helpers(storyboard):
    assert storyboard.scene_by_id("s1").title == "进门"
    assert storyboard.shot_by_id("s2sh1").action == "咖啡杯被放上桌面"
    assert storyboard.scene_by_id("nope") is None
    assert storyboard.shot_by_id("nope") is None


def test_character_bible_prompt_and_report():
    b = S.CharacterBible(name="少女", character_id="c1", speaker_id="S1")
    b.traits.append(S.CharacterTrait(name="hair", value="长黑发", category="stable", confidence=0.9))
    b.traits.append(S.CharacterTrait(name="mood", value="未知", category="uncertain", confidence=0.1))
    assert "长黑发" in b.character_prompt()
    assert "未知" not in b.character_prompt()
    b.conflicts.append(S.CharacterConflict(trait_name="hair", values=["黑", "棕"], reason="来源冲突"))
    assert "hair" in b.conflict_report_text()
    assert len(b.uncertain_traits()) == 1


def test_manifest_merge_dedupe():
    m1 = S.ReferenceManifest()
    m1.assets.append(S.AssetRef(asset_id="a1", path_or_ref="p1.png"))
    m2 = S.ReferenceManifest()
    m2.assets.append(S.AssetRef(asset_id="a1", path_or_ref="p1.png"))
    m2.assets.append(S.AssetRef(asset_id="a2", path_or_ref="p2.png"))
    m1.merge(m2)
    assert len(m1.assets) == 2
    assert m1.asset_by_id("a2") is not None


def test_h3_plan_basics():
    plan = S.H3PromptPlan(mode="FL2VA", duration_seconds=8.0)
    assert plan.mode == "FL2VA"
    assert S.R2V_SECTIONS[0] == "subject_definitions"
    assert len(S.THREE_FIELDS) == 3
    assert S.H3PromptPlan.from_json(plan.to_json()).duration_seconds == 8.0


def test_profile_advanced_sampling_fields_roundtrip():
    from aps.schemas.profile import AIProfile
    p = AIProfile(profile_id="p1", temperature=0.7, top_p=0.9,
                  frequency_penalty=0.2, presence_penalty=0.0,
                  max_tokens=2048, supports_vision=True, supports_files=True)
    restored = AIProfile.from_json(p.to_json())
    assert restored.temperature == 0.7
    assert restored.top_p == 0.9
    assert restored.frequency_penalty == 0.2
    assert restored.presence_penalty == 0.0
    assert restored.max_tokens == 2048
    assert restored.supports_vision is True
    assert restored.supports_files is True
    # 默认 None = 不发送采样参数（provider 默认值）
    d = AIProfile(profile_id="p2")
    assert d.temperature is None and d.max_tokens is None

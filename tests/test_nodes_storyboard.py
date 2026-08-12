"""Storyboard Builder 的生产请求接线测试。"""
import json

import aps.nodes.storyboard_builder as storyboard_mod
from aps.schemas.character import CharacterBible, CharacterBook, CharacterTrait
from aps.schemas.results import LLMResult
from aps.services import supplements


def setup_profile(store):
    store.create_profile({"profile_id": "p1", "name": "Storyboard test"})
    store.set_api_key("p1", "sk-abcdef1234567890")
    return store.get_profile("p1").node_payload()


def valid_storyboard_text():
    return json.dumps({
        "title": "雨夜",
        "characters": ["char_rin"],
        "character_definitions": [],
        "scenes": [{
            "scene_id": "s1",
            "title": "街口",
            "location": "街口",
            "characters": ["char_rin"],
            "shots": [{
                "shot_id": "s1sh1",
                "summary": "小凛等候",
                "action": "小凛看向街角",
                "characters": ["char_rin"],
                "audio": ["雨声"],
                "duration": 6,
            }],
        }],
    }, ensure_ascii=False)


def test_storyboard_builder_sends_role_table_and_character_contract(monkeypatch, store):
    """角色书约束必须进入真实节点的 Gateway 请求，而不是只存在辅助函数。"""
    payload = setup_profile(store)
    book = CharacterBook()
    bible = CharacterBible(character_id="char_rin", name="小凛", speaker_id="S1")
    bible.traits.extend([
        CharacterTrait(name="hair", value="短黑发", category="stable"),
        CharacterTrait(name="outfit", value="蓝色外套", category="current"),
    ])
    book.upsert_character(bible)
    book.assign_speaker_ids()

    captured = {}

    class FakeGateway:
        def generate(self, profile, api_key, req):
            captured["profile"] = profile
            captured["req"] = req
            return LLMResult(text=json.dumps({
                "title": "雨夜",
                "characters": ["char_rin", "char_new"],
                "character_definitions": [
                    {"character_id": "char_new", "name": "阿岚"},
                ],
                "scenes": [{
                    "scene_id": "s1",
                    "title": "街口",
                    "location": "街口",
                    "characters": ["char_rin", "char_new"],
                    "shots": [{
                        "shot_id": "s1sh1",
                        "summary": "小凛等候",
                        "action": "小凛看向街角",
                        "characters": ["char_rin", "char_new"],
                        "audio": ["雨声"],
                        "duration": 6,
                    }],
                }],
            }, ensure_ascii=False), profile_id="p1")

    monkeypatch.setattr(storyboard_mod, "Gateway", lambda: FakeGateway())
    result = storyboard_mod.APS_StoryboardBuilder().build(
        AI_PROFILE=payload,
        story_text="小凛在雨夜等候，阿岚从街角走来。",
        split_mode="shot",
        target_duration=6.0,
        max_scenes=2,
        style="",
        character_book=book.to_json(),
    )

    request = captured["req"]
    task_data = request.messages[0].content
    assert "character_role_table" in task_data
    assert "char_rin (S1, 小凛)" in task_data
    assert "stable: 短黑发" in task_data
    assert "character_definitions" in request.system
    assert "reuse those IDs exactly" in request.system
    assert "shot or beat audio arrays" in request.system

    storyboard = result[0]
    assert storyboard["character_definitions"] == [
        {"schema_version": "1.0", "character_id": "char_new", "name": "阿岚"},
        {"schema_version": "1.0", "character_id": "char_rin", "name": "小凛"},
    ]
    assert storyboard["scenes"][0]["shots"][0]["audio"] == ["雨声"]


def test_storyboard_builder_retries_once_after_invalid_json(monkeypatch, store):
    payload = setup_profile(store)
    responses = iter([LLMResult(text="不是 JSON", profile_id="p1"),
                      LLMResult(text=valid_storyboard_text(), profile_id="p1")])
    requests = []

    class FakeGateway:
        def generate(self, profile, api_key, req):
            requests.append(req)
            return next(responses)

    monkeypatch.setattr(storyboard_mod, "Gateway", lambda: FakeGateway())
    result = storyboard_mod.APS_StoryboardBuilder().build(
        AI_PROFILE=payload, story_text="小凛在雨夜等候。", split_mode="shot",
        target_duration=6.0, max_scenes=2, style="", retry_on_invalid=True)

    assert len(requests) == 2
    assert "previous response failed the declared output contract" in requests[1].system
    assert "[OPERATION:operation.protocol_retry@1.0]" in requests[1].system
    assert result[0]["scenes"][0]["shots"][0]["audio"] == ["雨声"]
    continuity = json.loads(result[2])
    assert any("重试 1 次并成功" in item["note"] for item in continuity)


def test_storyboard_builder_can_disable_invalid_json_retry(monkeypatch, store):
    payload = setup_profile(store)
    calls = []

    class FakeGateway:
        def generate(self, profile, api_key, req):
            calls.append(req)
            return LLMResult(text="不是 JSON", profile_id="p1")

    monkeypatch.setattr(storyboard_mod, "Gateway", lambda: FakeGateway())
    result = storyboard_mod.APS_StoryboardBuilder().build(
        AI_PROFILE=payload, story_text="保留原故事。", split_mode="shot",
        target_duration=4.0, max_scenes=1, style="", retry_on_invalid=False)

    assert len(calls) == 1
    assert result[0]["scenes"][0]["shots"][0]["summary"] == "保留原故事。"
    continuity = json.loads(result[2])
    assert any("未开启重试" in item["note"] for item in continuity)


def test_storyboard_builder_injects_explicit_markdown_supplement(monkeypatch, store, tmp_path):
    """Storyboard 的 Markdown 参考必须走真实 PromptAssembly，而非测试旁路。"""
    payload = setup_profile(store)
    monkeypatch.setattr(supplements, "supplements_dir",
                        lambda: tmp_path / "prompt_supplements")
    record = supplements.import_supplement({
        "supplement_id": "storyboard-rules",
        "title": "分镜规则",
        "filename": "storyboard-rules.md",
        "content": "每个镜头只保留一个明确动作，并继承上一镜的位置。",
        "scope": "node",
        "node_ids": ["storyboard.create"],
    })
    captured = {}

    class FakeGateway:
        def generate(self, profile, api_key, req):
            captured["req"] = req
            return LLMResult(text=valid_storyboard_text(), profile_id="p1")

    monkeypatch.setattr(storyboard_mod, "Gateway", lambda: FakeGateway())
    storyboard_mod.APS_StoryboardBuilder().build(
        AI_PROFILE=payload, story_text="小凛在雨夜等候。", split_mode="shot",
        target_duration=6.0, max_scenes=2, style="",
        prompt_supplements=record.supplement_id)

    request = captured["req"]
    assert "每个镜头只保留一个明确动作" in request.system
    assert any(item["source_id"] == "supplement.storyboard-rules"
               for item in request.assembly_report["sources"])

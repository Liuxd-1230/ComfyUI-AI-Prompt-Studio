"""Storyboard Builder 的生产请求接线测试。"""
import json

import aps.nodes.storyboard_builder as storyboard_mod
from aps.schemas.character import CharacterBible, CharacterBook, CharacterTrait
from aps.schemas.results import LLMResult


def setup_profile(store):
    store.create_profile({"profile_id": "p1", "name": "Storyboard test"})
    store.set_api_key("p1", "sk-abcdef1234567890")
    return store.get_profile("p1").node_payload()


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

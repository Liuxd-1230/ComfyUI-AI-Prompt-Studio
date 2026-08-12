"""分镜解析服务测试：JSON 容错 / 连续性 / 提示词构造。"""
import json

import pytest

from aps.schemas.storyboard import StoryCharacter, Storyboard
from aps.services.storyboard import (
    STORYBOARD_SCHEMA,
    bind_character_book,
    build_continuity,
    build_storyboard_prompt,
    normalize_storyboard,
    parse_storyboard_json,
)


def test_storyboard_schema_is_valid_for_strict_json_endpoints():
    """OpenAI strict 要求每个 object 的 required 覆盖全部 properties。"""
    def assert_strict(node, path="root"):
        if node.get("type") == "object":
            properties = node.get("properties", {})
            assert node.get("additionalProperties") is False, path
            assert set(node.get("required", [])) == set(properties), path
            for name, child in properties.items():
                if isinstance(child, dict):
                    assert_strict(child, f"{path}.{name}")
        elif node.get("type") == "array" and isinstance(node.get("items"), dict):
            assert_strict(node["items"], f"{path}[]")

    assert_strict(STORYBOARD_SCHEMA)

VALID = {
    "title": "咖啡店",
    "characters": ["c1", "c2"],
    "scenes": [
        {"scene_id": "s1", "title": "进门", "location": "咖啡店", "synopsis": "少女走进",
         "characters": ["c1"],
         "shots": [{"shot_id": "s1sh1", "summary": "全景", "action": "推门",
                    "camera": "wide", "duration": 3.0, "characters": ["c1"],
                    "beats": [{"text": "开门声", "kind": "action"}]}]},
        {"scene_id": "s2", "title": "落座", "location": "咖啡店", "synopsis": "点单",
         "characters": ["c1", "c2"],
         "shots": [{"shot_id": "s2sh1", "summary": "特写", "action": "放杯",
                    "characters": ["c1", "c2"]}]},
    ],
}


def test_parse_valid():
    sb = parse_storyboard_json(json.dumps(VALID), "scene", style="Cinematic")
    assert sb.title == "咖啡店"
    assert sb.split_mode == "scene"
    assert len(sb.scenes) == 2
    assert sb.scenes[0].shots[0].shot_id == "s1sh1"
    assert sb.scenes[0].shots[0].beats[0].kind == "action"
    assert sb.scenes[1].shots[0].duration > 0
    assert sb.all_character_ids() == ["c1", "c2"]


def test_parse_fenced_json():
    sb = parse_storyboard_json("```json\n" + json.dumps(VALID) + "\n```", "shot")
    assert len(sb.scenes) == 2


def test_parse_invalid_raises():
    with pytest.raises(ValueError, match="JSON"):
        parse_storyboard_json("不是 JSON", "scene")


def test_parse_missing_ids_fallback():
    data = {"scenes": [{"shots": [{}]}]}
    sb = parse_storyboard_json(json.dumps(data), "scene")
    assert sb.scenes[0].scene_id == "s1"
    assert sb.scenes[0].shots[0].shot_id == "s1sh1"


def test_parse_storyboard_reads_shot_and_beat_audio():
    data = {
        "title": "声音",
        "characters": [],
        "scenes": [{"scene_id": "s1", "shots": [{
            "shot_id": "sh1", "audio": ["雨声"],
            "beats": [{"text": "门响", "kind": "action", "audio": ["门轴声"]}],
        }]}],
    }
    sb = parse_storyboard_json(json.dumps(data), "beat")
    assert sb.scenes[0].shots[0].audio == ["雨声"]
    assert sb.scenes[0].shots[0].beats[0].audio == ["门轴声"]


def test_parse_storyboard_keeps_new_character_definitions():
    data = {
        "title": "重逢", "characters": ["char_01", "char_02"],
        "character_definitions": [
            {"character_id": "char_02", "name": "阿岚"},
        ],
        "scenes": [{"scene_id": "s1", "characters": ["char_01", "char_02"],
                    "shots": [{"shot_id": "sh1", "characters": ["char_02"]}]}],
    }
    sb = parse_storyboard_json(json.dumps(data), "shot")
    assert sb.character_definitions[0].character_id == "char_02"
    assert sb.character_definitions[0].name == "阿岚"


def test_storyboard_character_definition_roundtrips():
    sb = Storyboard(character_definitions=[StoryCharacter(character_id="c1", name="A")])
    restored = Storyboard.from_json(sb.to_json())
    assert restored.character_definitions[0].name == "A"


def test_bind_character_book_is_authoritative_for_used_ids():
    from aps.schemas.character import CharacterBook, CharacterBible

    sb = Storyboard(characters=["c1"], character_definitions=[
        StoryCharacter(character_id="c1", name="错误名字")])
    book = CharacterBook.from_bible(CharacterBible(character_id="c1", name="正确名字"))
    warnings = bind_character_book(sb, book)
    assert sb.character_definitions[0].name == "正确名字"
    assert warnings and "CharacterBook" in warnings[0]


def test_normalize_storyboard_enforces_limits_ids_and_duration():
    data = {
        "title": "长故事", "characters": ["c1"],
        "scenes": [
            {"scene_id": "dup", "location": "街道", "characters": ["c1"],
             "shots": [{"shot_id": "same", "duration": 2, "characters": ["c1"]}]},
            {"scene_id": "dup", "location": "室内", "shots": [
                {"shot_id": "same", "duration": 3, "characters": ["c1"]},
            ]},
            {"scene_id": "s3", "shots": [{"shot_id": "sh3", "duration": 4}]},
        ],
    }
    sb = parse_storyboard_json(json.dumps(data), "shot")
    warnings = normalize_storyboard(sb, max_scenes=2, target_duration=10.0)

    assert len(sb.scenes) == 2
    assert len({scene.scene_id for scene in sb.scenes}) == 2
    shot_ids = [shot.shot_id for scene in sb.scenes for shot in scene.shots]
    assert len(shot_ids) == len(set(shot_ids))
    assert round(sum(shot.duration for scene in sb.scenes for shot in scene.shots), 3) == 10.0
    assert sb.scenes[0].characters == ["c1"]
    assert any("max_scenes" in warning for warning in warnings)
    assert any("ID" in warning for warning in warnings)


def test_normalize_storyboard_creates_selectable_shot_for_empty_scene():
    sb = Storyboard(title="空场景", scenes=[
        # 一个模型可能返回只有场景没有 shots；不能让下游 Select/H3 丢掉它。
        __import__("aps.schemas.storyboard", fromlist=["Scene"]).Scene(
            scene_id="s1", index=1, synopsis="人物走进房间")
    ])
    warnings = normalize_storyboard(sb, max_scenes=3, target_duration=4.0)
    assert len(sb.scenes[0].shots) == 1
    assert sb.scenes[0].shots[0].summary == "人物走进房间"
    assert sb.scenes[0].shots[0].duration == 4.0
    assert any("没有镜头" in warning for warning in warnings)


def test_build_continuity():
    sb = parse_storyboard_json(json.dumps(VALID), "scene")
    notes = build_continuity(sb)
    assert any(n.character_id == "c1" and len(n.scene_ids) > 1 for n in notes)


def test_build_prompt_contains_requirements():
    p = build_storyboard_prompt("故事文本", "shot", 12.0, 8, "Cinematic")
    assert "JSON" in p
    assert "shot_id" in p
    assert "目标时长" in p
    assert "ANIMA" not in p and "H3" not in p  # 模型无关


def test_build_prompt_with_bible():
    from aps.schemas.character import CharacterBible

    b = CharacterBible(character_id="c1", name="少女")
    b.traits.append(__trait("hair", "long dark hair"))
    p = build_storyboard_prompt("故事", "scene", 5, 3, "", b)
    assert "long dark hair" in p
    assert "c1" in p


def test_build_prompt_with_manifest_character_table():
    """Manifest 的 character 类 Subject 应补成角色表并沿用真实 subject_id。"""
    from aps.schemas.references import AssetRef, ReferenceManifest, SubjectRef

    m = ReferenceManifest()
    m.add_asset(AssetRef(asset_id="img_0", asset_type="image", path_or_ref="ref0"))
    m.subjects.append(SubjectRef(subject_id="Subject 1", kind="character",
                                 definition="young woman, red hair"))
    m.subjects.append(SubjectRef(subject_id="Subject 2", kind="scene",
                                 definition="street at night"))
    p = build_storyboard_prompt("故事", "scene", 5, 3, "", None, None, m)
    assert "Subject 1" in p
    assert "角色表（来自参考清单" in p
    assert "young woman, red hair" in p
    assert "img_0" in p and "street at night" in p   # 非人物 Subject 仍进参考资产块


def test_build_prompt_manifest_with_book_prefers_book_table():
    """已有 CharacterBook 时角色表以 book 为准，Manifest 人物不再重复注入。"""
    from aps.schemas.character import CharacterBook
    from aps.schemas.references import ReferenceManifest, SubjectRef

    book = CharacterBook()
    book.upsert_character(__bible("c1", "red hair"))
    m = ReferenceManifest()
    m.subjects.append(SubjectRef(subject_id="Subject 1", kind="character",
                                 definition="blonde hair"))
    p = build_storyboard_prompt("故事", "scene", 5, 3, "", None, book, m)
    assert "角色表（ID 与稳定特征" in p          # book 的角色表
    assert "角色表（来自参考清单" not in p         # 不重复注入
    assert "blonde hair" not in p


def __bible(cid, hair):
    from aps.schemas.character import CharacterBible

    b = CharacterBible(character_id=cid, name=cid)
    b.traits.append(__trait("hair", hair))
    return b


def __trait(name, value):
    from aps.schemas.character import CharacterTrait

    return CharacterTrait(name=name, value=value)

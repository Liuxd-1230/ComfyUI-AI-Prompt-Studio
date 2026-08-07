"""分镜解析服务测试：JSON 容错 / 连续性 / 提示词构造。"""
import json

import pytest

from aps.schemas.storyboard import Storyboard
from aps.services.storyboard import (
    build_continuity,
    build_storyboard_prompt,
    parse_storyboard_json,
)

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

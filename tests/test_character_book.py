"""CharacterBook 数据链测试：upsert 去重、Speaker ID 唯一/稳定/冲突修复、节点双路输出。"""
import json

import aps.nodes.character_bible as cb_mod
from aps.schemas.character import CharacterBible, CharacterBook, CharacterTrait


def make_bible(cid, name, speaker_id=""):
    b = CharacterBible(character_id=cid, name=name, speaker_id=speaker_id)
    b.traits.append(CharacterTrait(name="hair", value=f"{name} hair",
                                   category="stable", locked=True))
    return b


def test_explicit_character_name_overrides_model_candidate_name():
    node = cb_mod.APS_CharacterBible()
    candidate = {
        "name": "model guess", "analysis_mode": "character_full",
        "traits": [], "sources": ["image_1"],
    }
    bible_json, _, _, _, _, _, _ = node.merge(
        "image_priority", character_candidate=candidate,
        character_name="参考人物")
    assert bible_json["name"] == "参考人物"


# ---------------------------------------------------------------- Speaker ID

def test_assign_speaker_ids_sequential():
    book = CharacterBook()
    book.characters = [make_bible("c1", "A"), make_bible("c2", "B"),
                       make_bible("c3", "C")]
    warnings = book.assign_speaker_ids()
    assert [c.speaker_id for c in book.characters] == ["S1", "S2", "S3"]
    assert warnings == []


def test_existing_speaker_ids_stable_and_new_gets_next_free():
    book = CharacterBook()
    book.characters = [make_bible("c1", "A", speaker_id="S3"),
                       make_bible("c2", "B", speaker_id="S1")]
    book.assign_speaker_ids()
    # c3 新人物：取下一个可用 ID（S2），不抢占已存在的 S1/S3
    book.upsert_character(make_bible("c3", "C"))
    book.assign_speaker_ids()
    assert book.speaker_id_for("c1") == "S3"
    assert book.speaker_id_for("c2") == "S1"
    assert book.speaker_id_for("c3") == "S2"


def test_speaker_conflict_repaired_with_warning():
    book = CharacterBook()
    book.characters = [make_bible("c1", "A", speaker_id="S1"),
                       make_bible("c2", "B", speaker_id="S1")]
    warnings = book.assign_speaker_ids()
    ids = {c.character_id: c.speaker_id for c in book.characters}
    assert ids["c1"] == "S1"
    assert ids["c2"] != "S1"          # 冲突被修复
    assert any("冲突" in w for w in warnings)


def test_invalid_speaker_id_reassigned_with_warning():
    book = CharacterBook()
    b = make_bible("c1", "A", speaker_id="SPEAKER")
    book.characters = [b]
    warnings = book.assign_speaker_ids()
    assert b.speaker_id == "S1"
    assert any("非法" in w for w in warnings)


def test_user_specified_valid_speaker_id_preserved():
    book = CharacterBook()
    book.characters = [make_bible("c1", "A", speaker_id="S9")]
    warnings = book.assign_speaker_ids()
    assert book.speaker_id_for("c1") == "S9"
    assert warnings == []


# ---------------------------------------------------------------- upsert

def test_upsert_no_duplicate_character_id():
    book = CharacterBook()
    book.upsert_character(make_bible("c1", "A"))
    book.upsert_character(make_bible("c2", "B"))
    book.upsert_character(make_bible("c1", "A2"))   # 同 ID 更新，不重复添加
    assert len(book.characters) == 2
    assert book.get_character("c1").name == "A2"


def test_upsert_preserves_assigned_speaker():
    book = CharacterBook()
    book.upsert_character(make_bible("c1", "A"))
    book.assign_speaker_ids()
    assert book.speaker_id_for("c1") == "S1"
    updated = make_bible("c1", "A2")   # 无 speaker_id
    book.upsert_character(updated)
    assert book.speaker_id_for("c1") == "S1"   # 保留稳定 ID


def test_upsert_requires_character_id():
    # CharacterBible.__post_init__ 总会生成 character_id，因此该保护分支不可达；
    # 这里验证保护逻辑本身存在（防御性，不依赖自动生成）。
    book = CharacterBook()
    raw = {"name": "x", "traits": []}
    # 直接构造绕过 __post_init__ 的对象，确认 upsert 拒绝
    b = CharacterBible.__new__(CharacterBible)
    for k, v in raw.items():
        setattr(b, k, v)
    b.speaker_id = ""
    b.character_id = ""
    b.default_character_id = ""
    try:
        book.upsert_character(b)
        assert False, "应抛 ValueError"
    except ValueError as exc:
        assert "character_id" in str(exc)


def test_context_text_contains_ids_and_traits():
    book = CharacterBook()
    book.characters = [make_bible("c1", "A"), make_bible("c2", "B")]
    book.assign_speaker_ids()
    ctx = book.context_text()
    assert "c1 (S1, A)" in ctx
    assert "c2 (S2, B)" in ctx
    assert "A hair" in ctx


def test_role_table_keeps_current_state_and_source_provenance():
    book = CharacterBook()
    bible = make_bible("c1", "A")
    bible.traits.extend([
        CharacterTrait(name="outfit", value="blue coat", category="current",
                       sources=["image_1"]),
        CharacterTrait(name="mood", value="tense", category="variable",
                       sources=["story_text"]),
        CharacterTrait(name="hair_color", value="possibly blonde", category="uncertain",
                       sources=["image_2"]),
    ])
    bible.sources = ["image_1", "story_text"]
    book.upsert_character(bible)
    book.assign_speaker_ids()

    table = book.role_table_text()

    assert "c1 (S1, A)" in table
    assert "stable: A hair" in table
    assert "current: blue coat" in table
    assert "variable: tense" in table
    assert "uncertain: possibly blonde" not in table
    assert "sources: image_1, story_text" in table


# ---------------------------------------------------------------- 节点双路输出

def test_bible_node_creates_book(store):
    node = cb_mod.APS_CharacterBible()
    _, _, json_out, _, _, book_json, warnings = node.merge(
        merge_strategy="consensus", character_candidate=None,
        existing_bible=None, existing_book=None, text_anchor="黑长直，圆脸",
        lock_fields="", character_name="少女")
    bible = CharacterBible.from_json(json.loads(json_out))
    book = CharacterBook.from_json(book_json)
    assert len(book.characters) == 1
    assert book.characters[0].character_id == bible.character_id
    assert book.speaker_id_for(bible.character_id) == "S1"
    assert warnings == ""


def test_bible_node_upserts_into_existing_book():
    node = cb_mod.APS_CharacterBible()
    book = CharacterBook()
    book.upsert_character(make_bible("char_A", "A"))
    book.upsert_character(make_bible("char_B", "B"))
    book.assign_speaker_ids()

    _, _, _, _, _, book_json, _ = node.merge(
        merge_strategy="consensus", character_candidate=None,
        existing_bible=None, existing_book=book.to_json(),
        text_anchor="金发", lock_fields="", character_name="C")
    new_book = CharacterBook.from_json(book_json)
    assert len(new_book.characters) == 3                      # 新增 C，不重复
    assert new_book.speaker_id_for("char_A") == "S1"
    assert new_book.speaker_id_for("char_B") == "S2"
    assert new_book.speaker_id_for(new_book.characters[-1].character_id) == "S3"


def test_bible_node_updates_existing_character_in_book():
    node = cb_mod.APS_CharacterBible()
    book = CharacterBook()
    book.upsert_character(make_bible("char_A", "A"))
    book.assign_speaker_ids()
    _, _, json_out, _, _, book_json, _ = node.merge(
        merge_strategy="consensus", character_candidate=None,
        existing_bible=None, existing_book=book.to_json(),
        text_anchor="蓝裙子", lock_fields="", character_name="A")
    new_book = CharacterBook.from_json(book_json)
    assert len(new_book.characters) == 1                      # 更新而非新增
    assert new_book.get_character("char_A").speaker_id == "S1"  # ID 稳定

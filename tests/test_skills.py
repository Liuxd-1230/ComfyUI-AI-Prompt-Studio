"""Skill 系统测试：加载 / 字段 / hash / 未知 id。"""
from aps.services.skills import get_skill, list_skill_ids, load_skills


def test_builtin_skills_loaded():
    skills = load_skills()
    assert "anima_expand" in skills
    assert "anima_rewrite" in skills
    assert "anima_repair" in skills
    assert "translate_en" in skills


def test_skill_fields():
    s = get_skill("anima_expand")
    assert s.id == "anima_expand"
    assert s.version == "1.0"
    assert s.target_family == "anima"
    assert s.renderer == "anima"
    assert "anima" in s.validators
    assert s.source == "builtin"
    assert s.system_prompt
    assert s.hash


def test_hash_stable_and_distinct():
    a = get_skill("anima_expand")
    b = get_skill("anima_expand")
    c = get_skill("anima_rewrite")
    assert a.hash == b.hash
    assert a.hash != c.hash


def test_unknown_skill_none():
    assert get_skill("nope") is None


def test_list_sorted():
    ids = list_skill_ids()
    assert ids == sorted(ids)
    assert "anima_expand" in ids

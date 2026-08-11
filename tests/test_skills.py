"""Skill 系统测试：加载 / 字段 / hash / 未知 id / 自定义技能管理（复制/新建/改/删/启停）。"""
import importlib

import pytest

skills_svc = importlib.import_module("aps.services.skills")
copy_builtin_to_custom = skills_svc.copy_builtin_to_custom
create_custom_skill = skills_svc.create_custom_skill
delete_custom_skill = skills_svc.delete_custom_skill
get_skill = skills_svc.get_skill
get_skill_record = skills_svc.get_skill_record
list_skill_ids = skills_svc.list_skill_ids
list_skill_records = skills_svc.list_skill_records
load_skills = skills_svc.load_skills
reset_cache = skills_svc.reset_cache
set_skill_enabled = skills_svc.set_skill_enabled
update_custom_skill = skills_svc.update_custom_skill
validate_skill_payload = skills_svc.validate_skill_payload


@pytest.fixture(autouse=True)
def _reset():
    reset_cache()
    yield
    reset_cache()


def test_builtin_skills_loaded():
    skills = load_skills()
    assert {"prompt_studio_anima", "prompt_studio_z_image",
            "prompt_studio_qwen_image_edit", "prompt_studio_generic_image",
            "minimax_h3_director"} <= set(skills)


def test_skill_fields():
    s = get_skill("prompt_studio_anima")
    assert s.id == "prompt_studio_anima"
    assert s.version == "1.0"
    assert s.target_family == "anima"
    assert s.renderer == "anima_plan"
    assert "anima" in s.validators
    assert s.source == "builtin"
    assert s.system_prompt
    assert s.hash


def test_anima_skill_requires_english_visual_output():
    """ANIMA 最终消费英文；中文只允许保留在专名和画面文字中。"""
    prompt = get_skill("prompt_studio_anima").system_prompt
    assert "Write every visual-description field in English" in prompt
    assert "names, proper nouns, reference" in prompt
    assert "labels, and quoted visible on-image text" in prompt


def test_hash_stable_and_distinct():
    a = get_skill("prompt_studio_anima")
    b = get_skill("prompt_studio_anima")
    c = get_skill("prompt_studio_z_image")
    assert a.hash == b.hash
    assert a.hash != c.hash


def test_unknown_skill_none():
    assert get_skill("nope") is None


def test_list_sorted():
    ids = list_skill_ids()
    assert ids == sorted(ids)
    assert "prompt_studio_anima" in ids


# ------------------------------------------------------------------ 自定义技能管理

def _custom_payload(sid="my_skill"):
    return {"id": sid, "version": "1.0", "target_family": "generic_image",
            "target_variant": "", "renderer": "generic",
            "system_prompt": "You are helpful.", "description": "测试技能"}


def _isolate_custom_skills(tmp_path, monkeypatch):
    assert get_skill.__globals__ is vars(skills_svc)
    directory = tmp_path / "skills"
    monkeypatch.setattr(skills_svc, "custom_skills_dir", lambda: directory)
    reset_cache()
    return directory


def test_validate_payload_rejects_bad_renderer():
    problems = validate_skill_payload({**_custom_payload(), "renderer": "hack"})
    assert any("renderer" in p for p in problems)


def test_validate_payload_rejects_unknown_fields():
    problems = validate_skill_payload({**_custom_payload(), "evil_field": "x"})
    assert any("未知字段" in p for p in problems)


def test_create_custom_skill(tmp_path, monkeypatch):
    _isolate_custom_skills(tmp_path, monkeypatch)
    create_custom_skill(_custom_payload())
    rec = get_skill_record("my_skill")
    assert rec["source"] == "custom"
    assert rec["enabled"] is True
    assert rec["system_prompt"] == "You are helpful."
    # 自定义覆盖同名内置（此场景无同名内置，仅验证存在于加载表）
    assert get_skill("my_skill").source == "custom"


def test_create_custom_skill_validation_error():
    with pytest.raises(ValueError):
        create_custom_skill({"id": "bad skill", "renderer": "nope", "system_prompt": ""})


def test_copy_builtin_then_edit(tmp_path, monkeypatch):
    _isolate_custom_skills(tmp_path, monkeypatch)
    rec = copy_builtin_to_custom("prompt_studio_anima")
    assert rec["source"] == "custom"
    assert rec["id"] == "prompt_studio_anima"
    updated = update_custom_skill("prompt_studio_anima",
                                  {**_custom_payload("prompt_studio_anima"),
                                   "version": "1.0", "renderer": "anima_plan",
                                   "target_family": "anima"})
    assert updated["version"] == "1.0"
    assert get_skill("prompt_studio_anima").source == "custom"


def test_update_builtin_readonly(tmp_path, monkeypatch):
    _isolate_custom_skills(tmp_path, monkeypatch)
    with pytest.raises(KeyError):
        update_custom_skill("prompt_studio_anima",
                            _custom_payload("prompt_studio_anima"))


def test_delete_custom_skill(tmp_path, monkeypatch):
    _isolate_custom_skills(tmp_path, monkeypatch)
    create_custom_skill(_custom_payload())
    assert get_skill("my_skill") is not None
    delete_custom_skill("my_skill")
    assert get_skill("my_skill") is None


def test_delete_builtin_readonly(tmp_path, monkeypatch):
    _isolate_custom_skills(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        delete_custom_skill("prompt_studio_anima")


def test_set_enabled_toggle(tmp_path, monkeypatch):
    _isolate_custom_skills(tmp_path, monkeypatch)
    create_custom_skill(_custom_payload())
    set_skill_enabled("my_skill", False)
    assert get_skill_record("my_skill")["enabled"] is False
    set_skill_enabled("my_skill", True)
    assert get_skill_record("my_skill")["enabled"] is True


def test_set_enabled_builtin_readonly(tmp_path, monkeypatch):
    _isolate_custom_skills(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        set_skill_enabled("prompt_studio_anima", False)


def test_list_records_include_source():
    records = list_skill_records()
    by_id = {r["id"]: r for r in records}
    assert by_id["prompt_studio_anima"]["source"] == "builtin"
    assert "hash" in by_id["prompt_studio_anima"]


def test_invalid_yaml_payload_is_not_loaded(tmp_path, monkeypatch):
    directory = _isolate_custom_skills(tmp_path, monkeypatch)
    directory.mkdir()
    (directory / "bad.yaml").write_text(
        "id: bad\nrenderer: executable\nsystem_prompt: x\n", encoding="utf-8")
    assert "bad" not in load_skills()


def test_nested_custom_skill_can_be_disabled_and_deleted(tmp_path, monkeypatch):
    directory = _isolate_custom_skills(tmp_path, monkeypatch) / "nested"
    directory.mkdir(parents=True)
    (directory / "nested_skill.yaml").write_text(
        "id: nested_skill\nrenderer: generic\ntarget_family: generic_image\n"
        "system_prompt: safe\nenabled: true\n", encoding="utf-8")
    assert get_skill("nested_skill") is not None
    set_skill_enabled("nested_skill", False)
    assert get_skill("nested_skill") is None
    delete_custom_skill("nested_skill")
    assert not (directory / "nested_skill.yaml").exists()

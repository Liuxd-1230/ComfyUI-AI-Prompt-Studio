"""安全测试：工作流 JSON 不含密钥 / 日志脱敏 / 非法 profile ID / 路径安全。"""
import json

import pytest

from aps.schemas.profile import AIProfile
from aps.services.secrets import mask_key, validate_profile_id


def test_workflow_json_never_contains_key(ext):
    prof = AIProfile(profile_id="p1", api_key_ref="sk-super-secret-123456")
    payload = prof.node_payload()
    workflow = json.dumps({
        "nodes": [{"type": "APS_ModelProfile", "widgets_values": ["p1"],
                   "outputs": [{"data": payload}]}],
        "extra": {},
    })
    assert "sk-super-secret" not in workflow
    assert "api_key_ref" not in workflow
    assert "profile_id" in workflow  # 只保存 profile_id


def test_secrets_file_separated_from_config(store):
    store.create_profile({"profile_id": "p1", "name": "DeepSeek"})
    store.set_api_key("p1", "sk-abcdef1234567890")
    config_text = (store.base_dir / "config.json").read_text(encoding="utf-8")
    secrets_text = (store.base_dir / "secrets.json").read_text(encoding="utf-8")
    assert "sk-abcdef" not in config_text
    assert "sk-abcdef" in secrets_text


def test_masked_api_key_in_list(store):
    store.create_profile({"profile_id": "p1"})
    store.set_api_key("p1", "sk-abcdef1234567890")
    profiles = store.list_profiles()
    assert profiles[0]["api_key_masked"] == "sk-***7890"
    assert profiles[0].get("api_key") is None


def test_mask_key():
    assert mask_key("sk-abcdef1234567890") == "sk-***7890"
    assert mask_key("short") == "***"
    assert mask_key("") == ""


def test_request_log_masked(store):
    store.append_request_log({"profile_id": "p1", "kind": "test",
                              "api_key": "sk-abcdef1234567890", "detail": "ok"})
    entry = store.get_request_log()[0]
    assert "sk-***7890" in str(entry)
    assert "sk-abcdef" not in str(entry)


def test_illegal_profile_ids_rejected():
    for bad in ["", "..", "../evil", "a/b", "a b", "a;rm", "x" * 65]:
        with pytest.raises(ValueError):
            validate_profile_id(bad)
    for good in ["prof_1", "A-B_c", "x" * 64]:
        assert validate_profile_id(good) == good


def test_path_traversal_profile_id_rejected(store):
    with pytest.raises(ValueError):
        store.create_profile({"profile_id": "../evil", "name": "x"})
    with pytest.raises(ValueError):
        store.get_profile("../evil")


def test_config_store_never_persists_api_key_field(store):
    store.create_profile({"profile_id": "p1", "api_key": "sk-abcdef1234567890",
                          "api_key_ref": "sk-abcdef1234567890"})
    raw = json.loads((store.base_dir / "config.json").read_text(encoding="utf-8"))
    profile_raw = raw["profiles"][0]
    assert "api_key" not in profile_raw
    assert "api_key_ref" not in profile_raw

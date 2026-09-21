"""配置存储测试：profile CRUD / 默认档案 / 能力缓存 / 请求日志。"""
import pytest

from aps.server import routes
from aps.server.config_store import ConfigStore


def test_crud_roundtrip(store):
    store.create_profile({"profile_id": "p1", "name": "DeepSeek", "model": "deepseek-v4-flash"})
    p = store.get_profile("p1")
    assert p.name == "DeepSeek" and p.model == "deepseek-v4-flash"
    assert p.base_url == "https://api.deepseek.com"  # 默认值

    store.update_profile("p1", {"model": "deepseek-v4-pro", "protocol": "chat_completions"})
    p = store.get_profile("p1")
    assert p.model == "deepseek-v4-pro" and p.protocol == "chat_completions"
    assert p.name == "DeepSeek"  # 未更新字段保留

    assert store.get_profile("nope") is None
    with pytest.raises(KeyError):
        store.delete_profile("nope")
    store.delete_profile("p1")
    assert store.get_profile("p1") is None


def test_duplicate_profile_rejected(store):
    store.create_profile({"profile_id": "p1"})
    with pytest.raises(ValueError):
        store.create_profile({"profile_id": "p1"})


@pytest.mark.parametrize("payload", [
    {"provider": "unknown"},
    {"base_url": "not-a-url"},
    {"timeout": 0},
    {"top_p": 1.5},
    {"frequency_penalty": 3},
])
def test_invalid_profile_is_rejected_on_save(store, payload):
    with pytest.raises(ValueError):
        store.create_profile({"profile_id": "bad", **payload})


def test_default_profile(store):
    assert store.get_default_profile() is None
    store.create_profile({"profile_id": "a"})
    store.create_profile({"profile_id": "b"})
    assert store.get_default_profile().profile_id == "a"  # 第一个成为默认
    store.set_default_profile("b")
    assert store.get_default_profile().profile_id == "b"
    with pytest.raises(KeyError):
        store.set_default_profile("nope")


def test_default_badge_follows_the_profile_nodes_will_use(store):
    """删掉默认档案后徽章不能消失：节点留空时真正用的是回退到的那个档案。"""
    store.create_profile({"profile_id": "a"})
    store.create_profile({"profile_id": "b"})
    store.delete_profile("a")
    assert store._config["default_profile_id"] == ""
    assert routes.handle_list_profiles(store)["default_profile_id"] == "b"

    routes.handle_set_default_profile("b", store)
    assert store._config["default_profile_id"] == "b"
    with pytest.raises(KeyError):
        routes.handle_set_default_profile("nope", store)


def test_set_settings_merges_by_key(store):
    """部分提交不能清空其余设置。"""
    store.set_settings({"theme": "dark", "last_tab": "profiles"})
    store.set_settings({"last_tab": "runtime"})
    assert store.get_settings() == {"theme": "dark", "last_tab": "runtime"}
    routes.handle_settings_set({"settings": {"theme": "light"}}, store)
    assert store.get_settings() == {"theme": "light", "last_tab": "runtime"}


def test_capability_cache(store):
    store.create_profile({"profile_id": "p1"})
    assert store.get_capabilities("p1") == {}


def test_capability_invalidation_uses_the_probe_fingerprint(store):
    """能力失效只由指纹判定：与能力无关的字段保存后探测结果仍然可用。"""
    store.create_profile({"profile_id": "p1", "model": "model-a", "timeout": 120})
    store.set_capabilities("p1", {"responses": True, "models": ["model-a"]})
    for patch in ({"timeout": 30}, {"temperature": 1.0}, {"web_search": "always"},
                  {"unload_policy": "after_success"}, {"search_url": "https://s.example"}):
        store.update_profile("p1", patch)
        assert store.get_capabilities("p1")["responses"] is True, patch
    store.update_profile("p1", {"supports_vision": True})
    assert store.get_capabilities("p1") == {}


def test_profile_or_key_change_invalidates_capabilities(store):
    store.create_profile({"profile_id": "p1", "model": "model-a"})
    store.set_capabilities("p1", {"models": ["model-a"], "responses": True})
    assert store.get_capabilities("p1")["responses"] is True
    store.update_profile("p1", {"model": "model-b"})
    assert store.get_capabilities("p1") == {}
    store.set_capabilities("p1", {"models": ["model-b"]})
    store.set_api_key("p1", "sk-new-123456789")
    assert store.get_capabilities("p1") == {}
    store.set_capabilities("p1", {"responses": True, "vision": False})
    assert store.get_capabilities("p1")["responses"] is True
    store.clear_capabilities("p1")
    assert store.get_capabilities("p1") == {}


def test_settings_roundtrip(store):
    assert store.get_settings() == {}
    store.set_settings({"lang": "zh", "theme": "dark"})
    assert store.get_settings()["lang"] == "zh"


def test_request_log_limited(store):
    for i in range(250):
        store.append_request_log({"profile_id": "p1", "kind": "test", "ok": True, "detail": str(i)})
    log = store.get_request_log(limit=500)
    assert len(log) <= 200
    assert len(store.get_request_log(limit=5)) == 5


def test_persistence_across_reopen(tmp_path):
    base = tmp_path / "cfg2"
    s1 = ConfigStore(base)
    s1.create_profile({"profile_id": "p1"})
    s1.set_api_key("p1", "sk-persist-12345678")
    s2 = ConfigStore(base)
    assert s2.get_profile("p1") is not None
    assert s2.get_api_key("p1") == "sk-persist-12345678"

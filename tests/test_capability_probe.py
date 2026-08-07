"""能力探测测试：mock requests，不触网。"""
import pytest
import requests

import aps.schemas as S
from aps.server import routes
from aps.services import capability_probe


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload or {}


def test_probe_success_deepseek(monkeypatch):
    profile = S.AIProfile(profile_id="p1", provider="deepseek")

    def fake_get(url, headers=None, timeout=None):
        assert url == "https://api.deepseek.com/models"
        assert headers["Authorization"].startswith("Bearer ")
        return FakeResponse(200, {"data": [{"id": "deepseek-v4-flash"}, {"id": "deepseek-v4-pro"}]})

    monkeypatch.setattr(requests, "get", fake_get)
    caps = capability_probe.probe_profile(profile, "sk-test")
    assert caps["auth_ok"] is True
    assert caps["model_listing"] is True
    assert "deepseek-v4-flash" in caps["models"]
    assert caps["responses"] is True
    assert caps["native_web_search"] is True
    assert caps["vision"] is False
    assert caps["error"] is None


def test_probe_generic_endpoint(monkeypatch):
    profile = S.AIProfile(profile_id="p1", provider="openai_compatible",
                          base_url="http://localhost:8000/v1")
    monkeypatch.setattr(requests, "get",
                        lambda *a, **k: FakeResponse(200, {"data": [{"id": "m"}]}))
    caps = capability_probe.probe_profile(profile, "key")
    assert caps["responses"] == "unknown"
    assert caps["chat_completions"] is True
    assert caps["native_web_search"] is False


def test_probe_vision_config_marked(monkeypatch):
    profile = S.AIProfile(profile_id="p1", vision_model="qwen-vl-max")
    monkeypatch.setattr(requests, "get",
                        lambda *a, **k: FakeResponse(200, {"data": []}))
    caps = capability_probe.probe_profile(profile, "key")
    assert caps["vision"] is True


def test_probe_auth_error_not_silent(monkeypatch):
    profile = S.AIProfile(profile_id="p1")
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(401))
    caps = capability_probe.probe_profile(profile, "bad-key")
    assert caps["auth_ok"] is False
    assert caps["http_status"] == 401
    assert "401" in caps["error"]


def test_probe_network_error(monkeypatch):
    profile = S.AIProfile(profile_id="p1")
    monkeypatch.setattr(requests, "get",
                        lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("down")))
    caps = capability_probe.probe_profile(profile, "key")
    assert caps["auth_ok"] is False
    assert "无法连接" in caps["error"]


def test_probe_no_key():
    profile = S.AIProfile(profile_id="p1")
    caps = capability_probe.probe_profile(profile, "")
    assert caps["error"] == "未配置 API Key，无法探测"


def test_merge_capabilities_keeps_unknown():
    old = {"responses": True, "vision": False}
    fresh = {"responses": "unknown", "vision": "unknown", "chat_completions": True}
    merged = capability_probe.merge_capabilities(old, fresh)
    assert merged["responses"] is True      # 旧值保留
    assert merged["vision"] is False
    assert merged["chat_completions"] is True


def test_route_handlers(store):
    store.create_profile({"profile_id": "p1", "name": "DeepSeek"})
    assert routes.handle_get_profile("p1", store)["profile_id"] == "p1"
    assert routes.handle_list_profiles(store)["profiles"][0]["profile_id"] == "p1"
    with pytest.raises(KeyError):
        routes.handle_get_profile("nope", store)

    r = routes.handle_set_api_key("p1", {"api_key": "sk-abc123456789"}, store)
    assert r["masked"] == "sk-***6789"
    assert routes.handle_get_profile("p1", store)["api_key_masked"] == "sk-***6789"

    routes.handle_clear_api_key("p1", store)
    assert store.get_api_key("p1") is None

    # 探测路由（无 key → 可读错误，不抛异常）
    result = routes.handle_probe("p1", store)
    assert result["ok"] is False

    assert routes.handle_status(store)["name"] == "AI Prompt Studio"

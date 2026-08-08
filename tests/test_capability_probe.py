"""能力探测测试：mock requests，不触网。"""
import pytest
import requests

import aps.schemas as S
from aps.server import routes
from aps.services import capability_probe


class FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload or {}


def chat_only_post(url, headers=None, json=None, timeout=None, **kwargs):
    """外部 HTTP 假服务：文本 Chat 可用，其余能力明确不可用。"""
    if url.endswith("/responses"):
        return FakeResponse(404, {"error": {"message": "not found"}}, "not found")
    content = (json.get("messages") or [{}])[-1].get("content", "")
    if isinstance(content, list):
        return FakeResponse(400, {"error": {"message": "multimodal unsupported"}})
    if json.get("response_format") or json.get("tools"):
        return FakeResponse(400, {"error": {"message": "parameter unsupported"}})
    return FakeResponse(200, {"choices": [{"message": {"content": "APS_OK"}}]})


def test_probe_route_actively_verifies_execution_capabilities(monkeypatch, store):
    """公开 probe 路由必须实测运行接口，并把每项收敛为 true/false。"""
    store.create_profile({
        "profile_id": "active", "provider": "openai_compatible",
        "base_url": "https://proxy.example/v1", "model": "model-a",
        "vision_model": "vision-a",
    })
    store.set_api_key("active", "secret")

    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(
        200, {"data": [{"id": "model-a"}, {"id": "vision-a"}]}))

    def fake_post(url, headers=None, json=None, timeout=None, **kwargs):
        if url.endswith("/responses"):
            return FakeResponse(404, {"error": {"message": "not found"}}, "not found")
        assert url.endswith("/chat/completions")
        message = (json.get("messages") or [{}])[-1]
        content = message.get("content", "")
        if json.get("response_format"):
            return FakeResponse(200, {"choices": [{"message": {"content": '{"aps_probe":"ok"}'}}]})
        if json.get("tools"):
            return FakeResponse(200, {"choices": [{"message": {"content": None, "tool_calls": [{
                "id": "call_1", "type": "function",
                "function": {"name": "aps_probe_tool", "arguments": "{}"},
            }]}}]})
        if isinstance(content, list) and any(part.get("type") == "image_url" for part in content):
            return FakeResponse(200, {"choices": [{"message": {"content": "MAGENTA"}}]})
        if isinstance(content, list) and any(part.get("type") == "file" for part in content):
            return FakeResponse(200, {"choices": [{"message": {"content": "APS_FILE_7D3C"}}]})
        return FakeResponse(200, {"choices": [{"message": {"content": "APS_OK"}}]})

    monkeypatch.setattr(requests, "post", fake_post)
    result = routes.handle_probe("active", store)

    assert result["ok"] is True
    expected = {
        "chat_completions": True, "responses": False,
        "structured_output_chat": True, "structured_output_responses": False,
        "function_tools": True, "native_web_search": False,
        "vision": True, "files": True, "vision_service": True,
    }
    assert {key: result[key] for key in expected} == expected
    assert all(value in (True, False) for value in expected.values())
    assert result["checks"]["chat_completions"]["endpoint"].endswith("/chat/completions")


def test_probe_rejects_schema_that_endpoint_silently_ignores(monkeypatch, store):
    store.create_profile({
        "profile_id": "plain", "provider": "openai_compatible",
        "base_url": "https://proxy.example/v1", "model": "model-a",
    })
    store.set_api_key("plain", "secret")
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(
        200, {"data": [{"id": "model-a"}]}))

    def plain_post(url, headers=None, json=None, timeout=None, **kwargs):
        if url.endswith("/responses"):
            return FakeResponse(404, text="missing")
        return FakeResponse(200, {"choices": [{"message": {
            "content": "I ignored the requested JSON format."}}]})

    monkeypatch.setattr(requests, "post", plain_post)
    result = routes.handle_probe("plain", store)
    assert result["chat_completions"] is True
    assert result["structured_output_chat"] is False
    assert result["json_output_chat"] is False
    assert "忽略" in result["checks"]["structured_output_chat"]["detail"]


def test_probe_updates_manual_vision_and_file_switches(monkeypatch, store):
    store.create_profile({
        "profile_id": "switches", "provider": "openai_compatible",
        "base_url": "https://proxy.example/v1", "model": "model-a",
        "supports_vision": True, "supports_files": True,
    })
    store.set_api_key("switches", "secret")
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(
        200, {"data": [{"id": "model-a"}]}))

    def text_only(url, headers=None, json=None, timeout=None, **kwargs):
        if url.endswith("/responses"):
            return FakeResponse(404, text="missing")
        content = (json.get("messages") or [{}])[-1].get("content", "")
        if isinstance(content, list):
            return FakeResponse(400, {"error": {"message": "multimodal unsupported"}})
        return FakeResponse(200, {"choices": [{"message": {"content": "APS_OK"}}]})

    monkeypatch.setattr(requests, "post", text_only)
    routes.handle_probe("switches", store)
    saved = store.get_profile("switches")
    assert saved.supports_vision is False
    assert saved.supports_files is False


def test_probe_uses_linked_vision_profile_endpoint_and_key(monkeypatch, store):
    store.create_profile({
        "profile_id": "vision", "provider": "openai_compatible",
        "base_url": "https://vision.example/v1", "model": "vision-a",
        "vision_model": "vision-a",
    })
    store.create_profile({
        "profile_id": "text", "provider": "openai_compatible",
        "base_url": "https://text.example/v1", "model": "text-a",
        "vision_profile_id": "vision",
    })
    store.set_api_key("text", "text-key")
    store.set_api_key("vision", "vision-key")

    def fake_get(url, headers=None, timeout=None):
        expected = "vision-key" if "vision.example" in url else "text-key"
        assert headers["Authorization"] == f"Bearer {expected}"
        model = "vision-a" if "vision.example" in url else "text-a"
        return FakeResponse(200, {"data": [{"id": model}]})

    def fake_post(url, headers=None, json=None, timeout=None, **kwargs):
        if "vision.example" in url:
            assert headers["Authorization"] == "Bearer vision-key"
            return FakeResponse(200, {"choices": [{"message": {"content": "MAGENTA"}}]})
        assert headers["Authorization"] == "Bearer text-key"
        if url.endswith("/responses"):
            return FakeResponse(404, text="missing")
        content = (json.get("messages") or [{}])[-1].get("content", "")
        if isinstance(content, list):
            return FakeResponse(400, text="no vision")
        if json.get("response_format") or json.get("tools"):
            return FakeResponse(400, text="unsupported")
        return FakeResponse(200, {"choices": [{"message": {"content": "APS_OK"}}]})

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "post", fake_post)
    result = routes.handle_probe("text", store)
    assert result["vision"] is False
    assert result["vision_service"] is True
    assert result["checks"]["vision_service"]["endpoint"].startswith("https://vision.example")


def test_probe_success_deepseek(monkeypatch):
    profile = S.AIProfile(profile_id="p1", provider="deepseek")

    def fake_get(url, headers=None, timeout=None):
        assert url == "https://api.deepseek.com/models"
        assert headers["Authorization"].startswith("Bearer ")
        return FakeResponse(200, {"data": [{"id": "deepseek-v4-flash"}, {"id": "deepseek-v4-pro"}]})

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "post", chat_only_post)
    caps = capability_probe.probe_profile(profile, "sk-test")
    assert caps["auth_ok"] is True
    assert caps["model_listing"] is True
    assert "deepseek-v4-flash" in caps["models"]
    assert caps["responses"] is False
    assert caps["chat_completions"] is True
    assert caps["native_web_search"] is False
    assert caps["vision"] is False
    assert caps["error"] is None


def test_probe_generic_endpoint(monkeypatch):
    profile = S.AIProfile(profile_id="p1", provider="openai_compatible",
                          base_url="http://localhost:8000/v1")
    monkeypatch.setattr(requests, "get",
                        lambda *a, **k: FakeResponse(200, {"data": [{"id": "m"}]}))
    monkeypatch.setattr(requests, "post", chat_only_post)
    caps = capability_probe.probe_profile(profile, "key")
    assert caps["responses"] is False
    assert caps["chat_completions"] is True
    assert caps["native_web_search"] is False
    assert caps["structured_output_responses"] is False
    assert caps["structured_output_chat"] is False


def test_third_party_deepseek_proxy_does_not_inherit_official_schema_caps(monkeypatch):
    profile = S.AIProfile(profile_id="p1", provider="deepseek",
                          base_url="https://tokenrhythm.studio/v1",
                          model="deepseek-v4-flash-0731")
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(
        200, {"data": [{"id": "deepseek-v4-flash-0731"}]}))
    monkeypatch.setattr(requests, "post", chat_only_post)
    caps = capability_probe.probe_profile(profile, "key")
    assert caps["capability_basis"] == "active_execution_probe"
    assert caps["structured_output_responses"] is False
    # 主动探测已验证的第三方 Schema 能力可以被网关使用。
    assert capability_probe.supports_native_structured_output(
        profile, {"structured_output_responses": True}, "responses") is True


def test_probe_deepseek_v4_pro_responses_false(monkeypatch):
    """能力按具体模型判定：v4-pro 当前不支持 Responses（官方 2026-08-07 查证）。"""
    profile = S.AIProfile(profile_id="p1", provider="deepseek",
                          model="deepseek-v4-pro")
    monkeypatch.setattr(requests, "get",
                        lambda *a, **k: FakeResponse(200, {"data": [{"id": "deepseek-v4-pro"}]}))
    monkeypatch.setattr(requests, "post", chat_only_post)
    caps = capability_probe.probe_profile(profile, "sk-test")
    assert caps["responses"] is False
    assert caps["chat_completions"] is True
    assert caps["native_web_search"] is False
    assert caps["capability_basis"] == "active_execution_probe"


def test_probe_deepseek_unknown_model_conservative(monkeypatch):
    """未知模型也以实际请求收敛成 bool。"""
    profile = S.AIProfile(profile_id="p1", provider="deepseek",
                          model="deepseek-xyz-new")
    monkeypatch.setattr(requests, "get",
                        lambda *a, **k: FakeResponse(200, {"data": []}))
    monkeypatch.setattr(requests, "post", chat_only_post)
    caps = capability_probe.probe_profile(profile, "sk-test")
    assert caps["responses"] is False
    assert caps["chat_completions"] is True
    assert caps["native_web_search"] is False
    assert caps["capability_basis"] == "active_execution_probe"


def test_deepseek_known_responses_table():
    assert capability_probe.deepseek_known_responses("deepseek-v4-flash") is False
    assert capability_probe.deepseek_known_responses("deepseek-v4-pro") is False
    assert capability_probe.deepseek_known_responses("deepseek-unknown") is None
    # 含变体后缀也能匹配（如 deepseek-v4-flash-ctx128k）
    assert capability_probe.deepseek_known_responses("deepseek-v4-flash-latest") is False


def test_probe_vision_config_marked(monkeypatch):
    profile = S.AIProfile(profile_id="p1", vision_model="qwen-vl-max")
    monkeypatch.setattr(requests, "get",
                        lambda *a, **k: FakeResponse(200, {"data": []}))
    monkeypatch.setattr(requests, "post", chat_only_post)
    caps = capability_probe.probe_profile(profile, "key")
    assert caps["vision"] is False
    assert caps["vision_configured"] is True


def test_probe_parses_models_shape_and_declared_modalities(monkeypatch):
    profile = S.AIProfile(profile_id="p1", provider="openai_compatible",
                          base_url="http://localhost:8000/v1", model="vision-model")
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(200, {
        "models": [{"key": "vision-model", "input_modalities": ["text", "image"]},
                   {"id": "text-model"}]}))
    def visual_post(url, headers=None, json=None, timeout=None, **kwargs):
        if url.endswith("/responses"):
            return FakeResponse(404, text="missing")
        content = (json.get("messages") or [{}])[-1].get("content", "")
        if isinstance(content, list) and any(part.get("type") == "image_url" for part in content):
            return FakeResponse(200, {"choices": [{"message": {"content": "MAGENTA"}}]})
        if json.get("response_format") or json.get("tools"):
            return FakeResponse(400, text="unsupported")
        return FakeResponse(200, {"choices": [{"message": {"content": "APS_OK"}}]})
    monkeypatch.setattr(requests, "post", visual_post)
    caps = capability_probe.probe_profile(profile, "key")
    assert caps["models"] == ["vision-model", "text-model"]
    assert caps["vision"] is True


def test_probe_auth_error_not_silent(monkeypatch):
    profile = S.AIProfile(profile_id="p1")
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(401))
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse(
        401, {"error": {"message": "invalid key"}}, "invalid key"))
    caps = capability_probe.probe_profile(profile, "bad-key")
    assert caps["auth_ok"] is False
    assert caps["http_status"] == 401
    assert caps["error_kind"] == "auth_error"
    assert "invalid key" in caps["error"]


def test_probe_network_error(monkeypatch):
    profile = S.AIProfile(profile_id="p1")
    def down(*args, **kwargs):
        raise requests.ConnectionError("down")
    monkeypatch.setattr(requests, "get", down)
    monkeypatch.setattr(requests, "post", down)
    caps = capability_probe.probe_profile(profile, "key")
    assert caps["auth_ok"] is False
    assert "ConnectionError" in caps["error"]


def test_probe_no_key():
    profile = S.AIProfile(profile_id="p1")
    caps = capability_probe.probe_profile(profile, "")
    assert caps["error"] == "未配置 API Key，无法探测"


def test_merge_capabilities_keeps_unknown():
    old = {"responses": True, "vision": False}
    fresh = {"responses": "unknown", "vision": "unknown", "chat_completions": True}
    merged = capability_probe.merge_capabilities(old, fresh)
    assert merged["responses"] == "unknown"  # 主动探测完整替换旧缓存
    assert merged["vision"] == "unknown"
    assert merged["chat_completions"] is True


def test_route_handlers(store):
    store.create_profile({"profile_id": "p1", "name": "DeepSeek"})
    assert routes.handle_get_profile("p1", store)["profile_id"] == "p1"
    assert routes.handle_list_profiles(store)["profiles"][0]["profile_id"] == "p1"
    with pytest.raises(KeyError):
        routes.handle_get_profile("nope", store)

    r = routes.handle_set_api_key("p1", {"api_key": "sk-abc123456789"}, store)
    assert r["masked"] == "sk-***6789"
    assert r["has_api_key"] is True
    public = routes.handle_get_profile("p1", store)
    assert public["api_key_masked"] == "sk-***6789"
    assert public["has_api_key"] is True

    cleared = routes.handle_clear_api_key("p1", store)
    assert cleared["has_api_key"] is False
    assert store.get_api_key("p1") is None

    # 探测路由（无 key → 可读错误，不抛异常）
    store.set_capabilities("p1", {"responses": True})
    result = routes.handle_probe("p1", store)
    assert result["ok"] is False
    assert store.get_capabilities("p1").get("responses") is False
    assert store.get_capabilities("p1").get("error")

    assert routes.handle_status(store)["name"] == "AI Prompt Studio"

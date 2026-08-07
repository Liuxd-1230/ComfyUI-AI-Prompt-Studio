"""运行时后端测试：mock requests.request，不触网。

覆盖：三后端 status/load/unload 的路径与请求体、模型不存在、不可达、
v0/v1 探测、unload_all、未知后端。
"""
import json

import pytest
import requests

from aps.services.runtime import create_backend


class FakeResp:
    def __init__(self, status=200, payload=None, text="", reason=""):
        self.status_code = status
        self._payload = payload
        self.text = text
        self.reason = reason

    def json(self):
        return self._payload or {}


def make_request_fake(monkeypatch, responder=None):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, "kwargs": kwargs})
        if responder is not None:
            return responder(method, url, **kwargs)
        return FakeResp(200, {})

    monkeypatch.setattr(requests, "request", fake_request)
    return calls


def test_ollama_status(monkeypatch):
    calls = make_request_fake(
        monkeypatch,
        responder=lambda m, u, **k: FakeResp(
            200, {"models": [{"name": "llama3"}, {"name": "qwen2"}]}))
    backend = create_backend("ollama")
    st = backend.status()
    assert st["available"] is True
    assert st["models"] == ["llama3", "qwen2"]
    assert calls[0]["url"] == "http://127.0.0.1:11434/api/ps"


def test_ollama_load_and_unload_bodies(monkeypatch):
    calls = make_request_fake(monkeypatch)
    backend = create_backend("ollama")
    backend.load("llama3")
    backend.unload("llama3")
    assert calls[0]["url"].endswith("/api/generate")
    assert calls[0]["kwargs"]["json"]["model"] == "llama3"
    assert calls[0]["kwargs"]["json"]["keep_alive"] == "5m"
    assert calls[1]["kwargs"]["json"]["keep_alive"] == 0


def test_ollama_model_not_found(monkeypatch):
    def resp(m, u, **k):
        return FakeResp(404, text="model 'xxx' not found")

    make_request_fake(monkeypatch, responder=resp)
    res = create_backend("ollama").load("xxx")
    assert res["ok"] is False
    assert "不存在" in res["error"]


def test_llamacpp_load_unload(monkeypatch):
    calls = make_request_fake(monkeypatch)
    backend = create_backend("llamacpp")
    backend.load("q4.gguf")
    backend.unload("q4.gguf")
    assert calls[0]["url"] == "http://127.0.0.1:8080/models/load"
    # llama.cpp 官方 body 是 {"model": ...}（按 README/源码查证，非 {"id": ...}）
    assert calls[0]["kwargs"]["json"] == {"model": "q4.gguf"}
    assert calls[1]["url"] == "http://127.0.0.1:8080/models/unload"
    assert calls[1]["kwargs"]["json"] == {"model": "q4.gguf"}


def test_llamacpp_status_lists_ids(monkeypatch):
    make_request_fake(
        monkeypatch,
        responder=lambda m, u, **k: FakeResp(
            200, {"data": [{"id": "model-a"}, {"id": "model-b"}]}))
    st = create_backend("llamacpp").status()
    assert st["models"] == ["model-a", "model-b"]


def test_lmstudio_v1_load(monkeypatch):
    calls = []

    def responder(m, u, **k):
        calls.append(u)
        # 第一次探测 /api/v0/models 返回 404 → v1
        if u.endswith("/api/v0/models"):
            return FakeResp(404, text="not found")
        return FakeResp(200, {})

    make_request_fake(monkeypatch, responder=responder)
    res = create_backend("lmstudio").load("m1")
    assert res["ok"] is True
    assert any(u.endswith("/api/v1/models/load") for u in calls)


def test_lmstudio_v0_readonly(monkeypatch):
    def responder(m, u, **k):
        if u.endswith("/api/v0/models"):
            return FakeResp(200, {"data": [{"id": "m1"}]})
        return FakeResp(200, {})

    make_request_fake(monkeypatch, responder=responder)
    backend = create_backend("lmstudio")
    res = backend.load("m1")
    assert res["ok"] is False
    assert "只读" in res["error"]
    assert backend.status()["models"] == ["m1"]  # v0 状态可读


def test_unreachable(monkeypatch):
    def responder(m, u, **k):
        raise requests.ConnectionError("refused")

    make_request_fake(monkeypatch, responder=responder)
    st = create_backend("ollama").status()
    assert st["available"] is False
    assert "无法连接" in st["error"]


def test_unload_all(monkeypatch):
    loaded = []

    def responder(m, u, **k):
        if u.endswith("/api/ps"):
            return FakeResp(200, {"models": [{"name": "a"}, {"name": "b"}]})
        if u.endswith("/api/generate"):
            loaded.append(k["json"]["model"])
            return FakeResp(200, {})
        return FakeResp(200, {})

    make_request_fake(monkeypatch, responder=responder)
    res = create_backend("ollama").unload_all()
    assert res["ok"] is True
    assert loaded == ["a", "b"]


def test_create_backend_unknown_kind():
    with pytest.raises(ValueError):
        create_backend("bogus")


def test_create_backend_default_urls():
    assert create_backend("ollama").base_url == "http://127.0.0.1:11434"
    assert create_backend("llamacpp").base_url == "http://127.0.0.1:8080"
    assert create_backend("lmstudio").base_url == "http://127.0.0.1:1234"


# ------------------------------------------------------------------ Settings /runtime 路由（P0：必须调用同一服务层并真实执行）

def test_runtime_route_status_executes_service(monkeypatch, store):
    """/runtime 处理器真实调用共享服务层并执行 mock 运行时（非 stub）。"""
    from aps.server import routes
    calls = make_request_fake(
        monkeypatch,
        responder=lambda m, u, **k: FakeResp(
            200, {"models": [{"name": "llama3"}, {"name": "qwen2"}]}))
    res = routes.handle_runtime({"backend": "ollama", "action": "status",
                                 "url": "", "model": ""}, store)
    assert res["ok"] is True
    assert res["models"] == ["llama3", "qwen2"]
    assert calls[0]["url"].endswith("/api/ps")     # 真实走了 Ollama 后端
    assert res["action"] == "status"


def test_runtime_route_load_executes_service(monkeypatch, store):
    from aps.server import routes
    calls = make_request_fake(monkeypatch)
    res = routes.handle_runtime({"backend": "ollama", "action": "load",
                                 "url": "", "model": "llama3"}, store)
    assert res["ok"] is True
    assert res["result"]["ok"] is True
    assert calls[0]["kwargs"]["json"]["model"] == "llama3"
    assert calls[0]["kwargs"]["json"]["keep_alive"] == "5m"


def test_runtime_route_unload_all_executes_service(monkeypatch, store):
    from aps.server import routes
    make_request_fake(
        monkeypatch,
        responder=lambda m, u, **k: FakeResp(
            200, {"models": [{"name": "m1"}]})
        if u.endswith("/api/ps") else FakeResp(200, {}))
    res = routes.handle_runtime({"backend": "ollama", "action": "unload_all",
                                 "url": "", "model": ""}, store)
    assert res["ok"] is True
    assert res["unloaded"] == ["m1"]


def test_runtime_route_unknown_backend_readable(store):
    from aps.server import routes
    res = routes.handle_runtime({"backend": "bogus", "action": "status"}, store)
    assert res["ok"] is False
    assert "未知运行时后端" in res["error"]


# ------------------------------------------------------------------ 自定义兼容后端（真实适配器，非摆设选项）

def test_custom_backend_status_and_load(monkeypatch):
    calls = make_request_fake(
        monkeypatch,
        responder=lambda m, u, **k: FakeResp(
            200, {"data": [{"id": "q4.gguf"}]})
        if u.endswith("/v1/models") else FakeResp(200, {}))
    backend = create_backend("custom", "http://127.0.0.1:9999")
    st = backend.status()
    assert st["available"] is True
    assert st["models"] == ["q4.gguf"]
    res = backend.load("q4.gguf")
    assert res["ok"] is True
    assert calls[1]["url"] == "http://127.0.0.1:9999/models/load"
    assert calls[1]["kwargs"]["json"] == {"model": "q4.gguf"}


def test_custom_backend_unsupported_op_clear_error(monkeypatch):
    def resp(m, u, **k):
        return FakeResp(404, text="not found")

    make_request_fake(monkeypatch, responder=resp)
    backend = create_backend("custom", "http://127.0.0.1:9999")
    res = backend.load("m")
    assert res["ok"] is False
    assert "不支持 load 操作" in res["error"]     # 明确报错，不伪装成功

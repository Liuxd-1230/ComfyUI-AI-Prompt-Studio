"""Gateway 测试：协议选择 / 降级链（仅协议不支持降级）/ 错误直传 / 搜索策略接入。"""
import pytest

from aps.schemas.profile import AIProfile
from aps.schemas.results import LLMResult, make_error
from aps.services.adapters.base import ProtocolUnsupported
from aps.services.gateway import Gateway, GenerateRequest


class FakeAdapter:
    def __init__(self, name):
        self.name = name
        self.calls = []

    def generate(self, profile, api_key, **kw):
        self.calls.append(kw)
        return self._scripted()

    def _scripted(self):
        return LLMResult(profile_id="p1", protocol=self.name, text=f"from-{self.name}")

    def script(self, func):
        self._scripted = func
        return self


def test_protocol_from_capabilities(store):
    store.create_profile({"profile_id": "p1"})
    store.set_capabilities("p1", {"responses": True})
    gw = Gateway(store=store)
    r = FakeAdapter("responses")
    c = FakeAdapter("chat_completions")
    gw._responses = r
    gw._chat = c
    gw.generate(store.get_profile("p1"), "k", GenerateRequest())
    assert r.calls and not c.calls


def test_protocol_local_uses_chat(store):
    store.create_profile({"profile_id": "p1", "provider": "local"})
    gw = Gateway(store=store)
    r = FakeAdapter("responses")
    c = FakeAdapter("chat_completions")
    gw._responses = r
    gw._chat = c
    gw.generate(store.get_profile("p1"), "k", GenerateRequest())
    assert c.calls and not r.calls


def test_protocol_explicit_override(store):
    store.create_profile({"profile_id": "p1", "protocol": "chat_completions"})
    store.set_capabilities("p1", {"responses": True})
    gw = Gateway(store=store)
    r = FakeAdapter("responses")
    c = FakeAdapter("chat_completions")
    gw._responses = r
    gw._chat = c
    gw.generate(store.get_profile("p1"), "k", GenerateRequest())
    assert c.calls and not r.calls


def test_degrade_responses_to_chat_with_warning(store):
    store.create_profile({"profile_id": "p1"})
    store.set_capabilities("p1", {"responses": True})

    def fail_responses(*a, **k):
        raise ProtocolUnsupported("Responses 接口不可用 HTTP 404")

    r = FakeAdapter("responses").script(fail_responses)
    c = FakeAdapter("chat_completions")
    gw = Gateway(store=store)
    gw._responses = r
    gw._chat = c
    result = gw.generate(store.get_profile("p1"), "k", GenerateRequest())
    assert result.text == "from-chat_completions"
    assert any("降级" in w for w in result.warnings)
    assert c.calls and r.calls


def test_no_degrade_on_auth_error(store):
    store.create_profile({"profile_id": "p1"})
    store.set_capabilities("p1", {"responses": True})

    def auth_err(*a, **k):
        return LLMResult(profile_id="p1", error=make_error("auth_error", "401", 401))

    r = FakeAdapter("responses").script(auth_err)
    c = FakeAdapter("chat_completions")
    gw = Gateway(store=store)
    gw._responses = r
    gw._chat = c
    result = gw.generate(store.get_profile("p1"), "k", GenerateRequest())
    assert result.has_error() and result.error.kind == "auth_error"
    assert not c.calls  # 认证失败绝不降级重试


def test_no_degrade_on_server_error(store):
    store.create_profile({"profile_id": "p1"})
    store.set_capabilities("p1", {"responses": True})

    def server_err(*a, **k):
        return LLMResult(profile_id="p1", error=make_error("server_error", "500", 500))

    r = FakeAdapter("responses").script(server_err)
    c = FakeAdapter("chat_completions")
    gw = Gateway(store=store)
    gw._responses = r
    gw._chat = c
    result = gw.generate(store.get_profile("p1"), "k", GenerateRequest())
    assert result.has_error() and result.error.kind == "server_error"
    assert not c.calls


def test_both_protocols_unsupported(store):
    store.create_profile({"profile_id": "p1"})
    store.set_capabilities("p1", {"responses": True})
    r = FakeAdapter("responses").script(
        lambda *a, **k: (_ for _ in ()).throw(ProtocolUnsupported("r 不可用")))
    c = FakeAdapter("chat_completions").script(
        lambda *a, **k: (_ for _ in ()).throw(ProtocolUnsupported("c 不可用")))
    gw = Gateway(store=store)
    gw._responses = r
    gw._chat = c
    result = gw.generate(store.get_profile("p1"), "k", GenerateRequest())
    assert result.has_error()
    assert result.error.kind == "protocol_unsupported"
    assert "均不可用" in result.error.message


def test_web_search_off_passes_through(store):
    store.create_profile({"profile_id": "p1"})
    r = FakeAdapter("responses")
    gw = Gateway(store=store)
    gw._responses = r
    gw.generate(store.get_profile("p1"), "k",
                GenerateRequest(web_search="off"))
    assert r.calls[0]["web_search"] is False


def test_web_search_native_enabled(store):
    store.create_profile({"profile_id": "p1"})
    store.set_capabilities("p1", {"native_web_search": True})
    r = FakeAdapter("responses")
    gw = Gateway(store=store)
    gw._responses = r
    gw.generate(store.get_profile("p1"), "k",
                GenerateRequest(web_search="always"))
    assert r.calls[0]["web_search"] is True


def test_web_search_offline_degraded_warns(store):
    """端点不支持原生搜索 → 仍请求但关闭联网工具并带警告。"""
    store.create_profile({"profile_id": "p1"})
    store.set_capabilities("p1", {"native_web_search": False})
    r = FakeAdapter("responses")
    gw = Gateway(store=store)
    gw._responses = r
    result = gw.generate(store.get_profile("p1"), "k",
                         GenerateRequest(web_search="always"))
    assert r.calls[0]["web_search"] is False
    assert any("不支持原生联网" in w for w in result.warnings)

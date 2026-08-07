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


def test_protocol_deepseek_per_model_when_caps_unknown(store):
    """未探测时按具体模型兜底：v4-flash→responses；v4-pro 与未知模型→chat。"""
    gw = Gateway(store=store)

    def run(model, want_responses):
        store.create_profile({"profile_id": model, "model": model})
        r = FakeAdapter("responses")
        c = FakeAdapter("chat_completions")
        gw._responses = r
        gw._chat = c
        gw.generate(store.get_profile(model), "k", GenerateRequest())
        assert bool(r.calls) is want_responses
        assert bool(c.calls) is (not want_responses)

    run("deepseek-v4-flash", want_responses=True)
    run("deepseek-v4-pro", want_responses=False)
    run("deepseek-unknown-model", want_responses=False)


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


# ------------------------------------------------------------------ 结构化输出

def test_gateway_deepseek_schema_falls_back_to_prompt_constraint(store):
    """DeepSeek Chat 未文档化 json_schema → 不发送协议层 schema，改为提示词约束。"""
    store.create_profile({"profile_id": "p1"})  # provider=deepseek
    # chat 路径：structured_output_chat=False（Responses 虽支持，本协议不支持）
    store.set_capabilities("p1", {"responses": False, "chat_completions": True,
                                  "structured_output_responses": True,
                                  "structured_output_chat": False})
    gw = Gateway(store=store)
    r = FakeAdapter("chat")
    gw._chat = r
    req = GenerateRequest(messages=[], output_schema={"type": "object"})
    gw.generate(store.get_profile("p1"), "k", req)
    assert r.calls
    kw = r.calls[0]
    assert "output_schema" not in kw or kw.get("output_schema") is None
    assert "JSON Schema" in req.system      # 约束已注入 system
    assert req.json_mode is True


def test_gateway_openai_compatible_schema_reaches_adapter(store):
    """OpenAI 兼容端点 + 协议级 structured_output 能力 → 协议层 schema 透传。"""
    store.create_profile({"profile_id": "p1", "provider": "openai_compatible"})
    store.set_capabilities("p1", {"responses": True, "chat_completions": True,
                                  "structured_output_responses": True,
                                  "structured_output_chat": True})
    gw = Gateway(store=store)
    r = FakeAdapter("responses")
    gw._responses = r
    req = GenerateRequest(messages=[], output_schema={"type": "object"})
    gw.generate(store.get_profile("p1"), "k", req)
    kw = r.calls[0]
    assert kw["output_schema"] == {"type": "object"}
    assert "JSON Schema" not in req.system


def test_gateway_openai_chat_structured_output_reaches_adapter(store):
    """OpenAI 兼容 Chat 路径 + structured_output_chat → chat adapter 收到 schema。"""
    store.create_profile({"profile_id": "p1", "provider": "openai_compatible"})
    store.set_capabilities("p1", {"responses": False, "chat_completions": True,
                                  "structured_output_responses": True,
                                  "structured_output_chat": True})
    gw = Gateway(store=store)
    r = FakeAdapter("chat")
    gw._chat = r
    req = GenerateRequest(messages=[], output_schema={"type": "object"})
    gw.generate(store.get_profile("p1"), "k", req)
    kw = r.calls[0]
    assert kw["output_schema"] == {"type": "object"}
    assert "JSON Schema" not in req.system


def test_deepseek_flash_responses_structured_output(store):
    """0.2.1 P0-3：deepseek-v4-flash + Responses → 原生 text.format json_schema。"""
    store.create_profile({"profile_id": "p1", "provider": "deepseek",
                          "model": "deepseek-v4-flash"})
    store.set_capabilities("p1", {"responses": True, "chat_completions": True,
                                  "structured_output_responses": True,
                                  "structured_output_chat": False})
    gw = Gateway(store=store)
    r = FakeAdapter("responses")
    gw._responses = r
    req = GenerateRequest(messages=[], output_schema={"type": "object",
                                                     "properties": {}})
    gw.generate(store.get_profile("p1"), "k", req)
    kw = r.calls[0]
    assert kw["output_schema"] == {"type": "object", "properties": {}}
    assert "JSON Schema" not in req.system


def test_deepseek_chat_schema_fallback(store):
    """0.2.1 P0-3：deepseek chat_completions 未文档化 json_schema → 提示词约束。"""
    store.create_profile({"profile_id": "p1", "provider": "deepseek",
                          "model": "deepseek-v4-flash"})
    store.set_capabilities("p1", {"responses": False, "chat_completions": True,
                                  "structured_output_responses": True,
                                  "structured_output_chat": False})
    gw = Gateway(store=store)
    r = FakeAdapter("chat")
    gw._chat = r
    req = GenerateRequest(messages=[], output_schema={"type": "object"})
    gw.generate(store.get_profile("p1"), "k", req)
    kw = r.calls[0]
    assert "output_schema" not in kw or kw.get("output_schema") is None
    assert "JSON Schema" in req.system


def test_generic_openai_structured_output(store):
    """0.2.1 P0-3：通用 OpenAI 兼容端点在两个协议都走原生 schema。"""
    store.create_profile({"profile_id": "p1", "provider": "openai_compatible"})
    store.set_capabilities("p1", {"responses": True, "chat_completions": True,
                                  "structured_output_responses": True,
                                  "structured_output_chat": True})
    gw = Gateway(store=store)
    r = FakeAdapter("responses")
    gw._responses = r
    req = GenerateRequest(messages=[], output_schema={"type": "object"})
    gw.generate(store.get_profile("p1"), "k", req)
    assert r.calls[0]["output_schema"] == {"type": "object"}

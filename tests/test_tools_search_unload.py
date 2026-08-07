"""Batch C 收尾测试：外部搜索后端注入（C4）、函数工具循环（C5）、unload_policy（C2）。

覆盖：
- services/tools.py：工具定义、now / search / 未知工具执行（失败不抛异常不伪造）；
- gateway 外部搜索注入：配置 search_url → 结果块进最后一条 user 消息；失败 → 警告；
- gateway 工具循环：一轮工具 → 续轮 → 最终回答；达到 MAX_TOOL_ROUNDS → 截断警告；
- gateway unload_policy：after_request / after_success 只对 local 生效、失败只加警告；
- adapter 工具消息序列化（chat/responses 的 tool_calls / tool 消息结构）。
"""
import json

import pytest

from aps.schemas.profile import AIProfile
from aps.schemas.results import ChatMessage, LLMResult, ToolCall
from aps.services import tools as tools_svc
from aps.services.gateway import GenerateRequest, Gateway
from aps.services.tools import MAX_TOOL_ROUNDS


# ------------------------------------------------------------------ tools 注册表

def test_tool_definitions_shape():
    defs = tools_svc.tool_definitions()
    names = {d["name"] for d in defs}
    assert "now" in names and "search" in names
    for d in defs:
        assert d["description"] and d["parameters"] and isinstance(d["parameters"], dict)


def test_execute_now():
    out = tools_svc.execute_tool("now", "{}", AIProfile())
    assert out["ok"] is True and out["output"]


def test_execute_search_uses_profile_search_url(monkeypatch):
    calls = []

    def fake_external(url, query, api_key="", timeout=15.0):
        calls.append((url, query))
        return {"ok": True, "results": [{"title": "T", "url": "https://e/1",
                                         "snippet": "S"}]}

    monkeypatch.setattr("aps.services.tools.search.search_external", fake_external)
    out = tools_svc.execute_tool(
        "search", json.dumps({"query": "q1"}),
        AIProfile(profile_id="p1", search_url="http://127.0.0.1:9000/s"))
    assert out["ok"] is True
    assert calls == [("http://127.0.0.1:9000/s", "q1")]
    assert "https://e/1" in out["output"]


def test_execute_search_missing_query():
    out = tools_svc.execute_tool("search", "{}", AIProfile(search_url="http://x"))
    assert out["ok"] is False and "query" in out["error"]


def test_execute_search_no_search_url():
    out = tools_svc.execute_tool("search", '{"query": "x"}', AIProfile())
    assert out["ok"] is False and "search_url" in out["error"]


def test_execute_search_backend_error_not_faked(monkeypatch):
    monkeypatch.setattr("aps.services.tools.search.search_external",
                        lambda *a, **k: {"ok": False, "error": "HTTP 500"})
    out = tools_svc.execute_tool("search", '{"query": "x"}',
                                 AIProfile(search_url="http://x"))
    assert out["ok"] is False and "HTTP 500" in out["error"]


def test_execute_unknown_tool_error():
    out = tools_svc.execute_tool("bogus", "{}", AIProfile())
    assert out["ok"] is False and "未知工具" in out["error"]


def test_execute_bad_json_arguments_treated_empty():
    out = tools_svc.execute_tool("now", "not-json", AIProfile())
    assert out["ok"] is True  # 参数解析失败按空参数处理，不抛异常


# ------------------------------------------------------------------ C4 外部搜索注入

class _FakeAdapter:
    """可编程 adapter：记录参数，按脚本返回。"""

    def __init__(self, name):
        self.name = name
        self.calls = []
        self.scripted = None

    def generate(self, profile, api_key, **kw):
        self.calls.append(kw)
        if self.scripted is not None:
            return self.scripted(profile, api_key, kw)
        return LLMResult(profile_id=profile.profile_id, protocol=self.name,
                         text=f"from-{self.name}")

    def script(self, func):
        self.scripted = func
        return self


def _gw(store, responses_scripted=None, chat_scripted=None):
    gw = Gateway(store=store)
    r = _FakeAdapter("responses")
    c = _FakeAdapter("chat_completions")
    if responses_scripted:
        r.script(responses_scripted)
    if chat_scripted:
        c.script(chat_scripted)
    gw._responses = r
    gw._chat = c
    return gw, r, c


def test_gateway_external_search_injects_results(store, monkeypatch):
    """C4：无原生搜索 + 配置 search_url → 结果块注入最后一条 user 消息。"""
    store.create_profile({"profile_id": "p1", "search_url": "http://127.0.0.1:9000/s"})
    store.set_capabilities("p1", {"responses": True, "native_web_search": False})

    seen = []

    def fake_external(url, query, api_key="", timeout=15.0):
        seen.append((url, query))
        return {"ok": True, "results": [
            {"title": "结果一", "url": "https://e/1", "snippet": "摘要"}]}

    monkeypatch.setattr("aps.services.search.search_external", fake_external)

    gw, r, _ = _gw(store)
    req = GenerateRequest(
        messages=[ChatMessage(role="user", content="今天天气怎么样")],
        web_search="always")
    result = gw.generate(store.get_profile("p1"), "k", req)
    assert r.calls[0]["web_search"] is False          # 不用原生工具
    assert seen == [("http://127.0.0.1:9000/s", "今天天气怎么样")]
    last_user = req.messages[-1].content
    assert "联网搜索结果" in last_user
    assert "今天天气怎么样" in last_user
    assert "https://e/1" in last_user
    assert not result.warnings


def test_gateway_external_search_failure_warns(store, monkeypatch):
    """C4：外部搜索失败 → 明确警告，绝不伪造结果，请求照常执行。"""
    store.create_profile({"profile_id": "p1", "search_url": "http://127.0.0.1:9000/s"})
    store.set_capabilities("p1", {"responses": True, "native_web_search": False})
    monkeypatch.setattr("aps.services.search.search_external",
                        lambda *a, **k: {"ok": False, "error": "连接失败"})

    gw, r, _ = _gw(store)
    req = GenerateRequest(messages=[ChatMessage(role="user", content="q")],
                          web_search="always")
    result = gw.generate(store.get_profile("p1"), "k", req)
    assert any("外部搜索失败" in w for w in result.warnings)
    assert "联网搜索结果" not in req.messages[-1].content
    assert result.text == "from-responses"


def test_gateway_external_search_no_search_url_offline_warning(store):
    """C4：无原生搜索且未配置 search_url → 离线警告（与既有降级一致）。"""
    store.create_profile({"profile_id": "p1"})
    store.set_capabilities("p1", {"responses": True, "native_web_search": False})
    gw, r, _ = _gw(store)
    result = gw.generate(store.get_profile("p1"), "k",
                         GenerateRequest(web_search="always"))
    assert any("不支持原生联网搜索" in w for w in result.warnings)


def test_gateway_external_search_native_untouched(store):
    """原生可用时外部搜索不触发。"""
    store.create_profile({"profile_id": "p1"})
    store.set_capabilities("p1", {"responses": True, "native_web_search": True})
    gw, r, _ = _gw(store)
    gw.generate(store.get_profile("p1"), "k",
                GenerateRequest(web_search="always"))
    assert r.calls[0]["web_search"] is True
    assert "联网搜索结果" not in "".join(m.content for m in r.calls[0]["messages"] or [])


# ------------------------------------------------------------------ C5 工具循环

def test_gateway_tool_loop_one_round(store):
    """一轮工具调用：第一次返回 tool_calls，续轮返回最终文本。"""
    store.create_profile({"profile_id": "p1"})
    store.set_capabilities("p1", {"responses": True})
    calls = []

    def scripted(profile, api_key, kw):
        calls.append(kw)
        if len(calls) == 1:
            return LLMResult(profile_id="p1", protocol="responses",
                             tool_calls=[ToolCall(id="call_1", name="now",
                                                  arguments="{}")])
        return LLMResult(profile_id="p1", protocol="responses", text="现在是 12:00")

    gw, r, _ = _gw(store, responses_scripted=scripted)
    result = gw.generate(store.get_profile("p1"), "k",
                         GenerateRequest(tools=True))
    assert result.text == "现在是 12:00"
    assert not result.tool_calls
    # 续轮消息：assistant 携带 tool_calls + tool 结果
    msgs = calls[1]["messages"]
    assert msgs[-1].role == "tool"
    assert msgs[-1].tool_call_id == "call_1"
    assert msgs[-2].role == "assistant" and msgs[-2].tool_calls
    # 工具定义已随协议发送
    assert any(d["name"] == "now" for d in calls[0]["tool_defs"])


def test_gateway_tool_loop_round_cap_warns(store):
    """达到 MAX_TOOL_ROUNDS 仍返回 tool_calls → 截断警告（不静默丢弃）。"""
    store.create_profile({"profile_id": "p1"})
    store.set_capabilities("p1", {"responses": True})
    calls = []

    def scripted(profile, api_key, kw):
        calls.append(kw)
        return LLMResult(profile_id="p1", protocol="responses",
                         tool_calls=[ToolCall(id=f"call_{len(calls)}",
                                              name="now", arguments="{}")])

    gw, r, _ = _gw(store, responses_scripted=scripted)
    result = gw.generate(store.get_profile("p1"), "k",
                         GenerateRequest(tools=True))
    # 初始调用 + MAX_TOOL_ROUNDS 轮续调
    assert len(calls) == 1 + MAX_TOOL_ROUNDS
    assert any("已达上限" in w for w in result.warnings)


def test_gateway_tool_loop_off_no_loop(store):
    """tools=False → 不执行工具循环。"""
    store.create_profile({"profile_id": "p1"})
    store.set_capabilities("p1", {"responses": True})
    calls = []

    def scripted(profile, api_key, kw):
        calls.append(kw)
        return LLMResult(profile_id="p1", protocol="responses",
                         tool_calls=[ToolCall(id="c1", name="now", arguments="{}")])

    gw, r, _ = _gw(store, responses_scripted=scripted)
    result = gw.generate(store.get_profile("p1"), "k", GenerateRequest())
    assert len(calls) == 1
    assert result.tool_calls and result.tool_calls[0].name == "now"


def test_gateway_tool_loop_uses_search_tool(store, monkeypatch):
    """工具循环中 search 工具真实执行（走档案 search_url）。"""
    store.create_profile({"profile_id": "p1", "search_url": "http://127.0.0.1:9000/s"})
    store.set_capabilities("p1", {"responses": True})
    seen = []

    def fake_external(url, query, api_key="", timeout=15.0):
        seen.append(query)
        return {"ok": True, "results": [{"title": "T", "url": "https://e/1", "snippet": "S"}]}

    monkeypatch.setattr("aps.services.tools.search.search_external", fake_external)
    calls = []

    def scripted(profile, api_key, kw):
        calls.append(kw)
        if len(calls) == 1:
            return LLMResult(profile_id="p1", protocol="responses",
                             tool_calls=[ToolCall(id="c1", name="search",
                                                  arguments='{"query": "最新AI新闻"}')])
        return LLMResult(profile_id="p1", protocol="responses", text="已完成")

    gw, r, _ = _gw(store, responses_scripted=scripted)
    result = gw.generate(store.get_profile("p1"), "k",
                         GenerateRequest(tools=True))
    assert seen == ["最新AI新闻"]
    assert result.text == "已完成"
    assert "https://e/1" in calls[1]["messages"][-1].content


def test_gateway_tool_loop_error_continues(store):
    """工具执行失败 → 错误文本回给模型（模型可重试/停止），不抛异常。"""
    store.create_profile({"profile_id": "p1"})
    store.set_capabilities("p1", {"responses": True})
    calls = []

    def scripted(profile, api_key, kw):
        calls.append(kw)
        if len(calls) == 1:
            return LLMResult(profile_id="p1", protocol="responses",
                             tool_calls=[ToolCall(id="c1", name="bogus", arguments="{}")])
        return LLMResult(profile_id="p1", protocol="responses", text="工具不可用，停止")

    gw, r, _ = _gw(store, responses_scripted=scripted)
    result = gw.generate(store.get_profile("p1"), "k",
                         GenerateRequest(tools=True))
    assert result.text == "工具不可用，停止"
    assert "未知工具" in calls[1]["messages"][-1].content


# ------------------------------------------------------------------ C2 unload_policy

def test_unload_policy_after_request_local(store, monkeypatch):
    store.create_profile({"profile_id": "p1", "provider": "local",
                          "unload_policy": "after_request",
                          "model": "llama3",
                          "runtime": {"backend": "ollama", "url": "",
                                      "model": "llama3"}})
    store.set_capabilities("p1", {"responses": False})
    unloads = []

    def fake_unload(backend, action, url="", model=""):
        if action == "unload":
            unloads.append((backend, model))
            return {"ok": True}
        return {"ok": True}

    monkeypatch.setattr("aps.services.gateway.run_runtime_action", fake_unload)
    gw, _, c = _gw(store)
    result = gw.generate(store.get_profile("p1"), "k", GenerateRequest())
    assert result.text == "from-chat_completions"
    assert unloads == [("ollama", "llama3")]


def test_unload_policy_after_request_on_error(store, monkeypatch):
    """after_request：请求失败也卸载。"""
    store.create_profile({"profile_id": "p1", "provider": "local",
                          "unload_policy": "after_request",
                          "model": "m",
                          "runtime": {"backend": "ollama", "model": "m"}})
    store.set_capabilities("p1", {"responses": False})
    unloads = []
    monkeypatch.setattr("aps.services.gateway.run_runtime_action",
                        lambda b, a, url="", model="": (
                            unloads.append((b, model)) or {"ok": True}))
    gw, _, c = _gw(store, chat_scripted=lambda p, k, kw: LLMResult(
        profile_id="p1", protocol="chat_completions",
        error=__import__("aps.schemas.results", fromlist=["make_error"]).make_error(
            "server_error", "500", 500)))
    result = gw.generate(store.get_profile("p1"), "k", GenerateRequest())
    assert result.has_error()
    assert unloads == [("ollama", "m")]


def test_unload_policy_after_success_skips_on_error(store, monkeypatch):
    """after_success：请求失败不卸载。"""
    store.create_profile({"profile_id": "p1", "provider": "local",
                          "unload_policy": "after_success",
                          "model": "m",
                          "runtime": {"backend": "ollama", "model": "m"}})
    store.set_capabilities("p1", {"responses": False})
    unloads = []
    monkeypatch.setattr("aps.services.gateway.run_runtime_action",
                        lambda b, a, url="", model="": (
                            unloads.append(1) or {"ok": True}))
    gw, _, c = _gw(store, chat_scripted=lambda p, k, kw: LLMResult(
        profile_id="p1", protocol="chat_completions",
        error=__import__("aps.schemas.results", fromlist=["make_error"]).make_error(
            "server_error", "500", 500)))
    gw.generate(store.get_profile("p1"), "k", GenerateRequest())
    assert unloads == []


def test_unload_policy_never_no_op(store, monkeypatch):
    store.create_profile({"profile_id": "p1", "provider": "local",
                          "unload_policy": "never", "model": "m",
                          "runtime": {"backend": "ollama", "model": "m"}})
    store.set_capabilities("p1", {"responses": False})
    unloads = []
    monkeypatch.setattr("aps.services.gateway.run_runtime_action",
                        lambda b, a, url="", model="": (unloads.append(1) or {"ok": True}))
    gw, _, _ = _gw(store)
    gw.generate(store.get_profile("p1"), "k", GenerateRequest())
    assert unloads == []


def test_unload_policy_not_local_no_op(store, monkeypatch):
    """只对本地运行时生效。"""
    store.create_profile({"profile_id": "p1", "provider": "deepseek",
                          "unload_policy": "after_request"})
    store.set_capabilities("p1", {"responses": True})
    unloads = []
    monkeypatch.setattr("aps.services.gateway.run_runtime_action",
                        lambda b, a, url="", model="": (unloads.append(1) or {"ok": True}))
    gw, _, _ = _gw(store)
    gw.generate(store.get_profile("p1"), "k", GenerateRequest())
    assert unloads == []


def test_unload_policy_failure_warns_not_fails(store, monkeypatch):
    """卸载失败 → 追加警告，请求结果不受影响。"""
    store.create_profile({"profile_id": "p1", "provider": "local",
                          "unload_policy": "after_request", "model": "m",
                          "runtime": {"backend": "ollama", "model": "m"}})
    store.set_capabilities("p1", {"responses": False})
    monkeypatch.setattr("aps.services.gateway.run_runtime_action",
                        lambda b, a, url="", model="": {"ok": False, "error": "无法连接"})
    gw, _, _ = _gw(store)
    result = gw.generate(store.get_profile("p1"), "k", GenerateRequest())
    assert not result.has_error()
    assert any("卸载失败" in w for w in result.warnings)


# ------------------------------------------------------------------ adapter 工具消息序列化

def _chat_adapter_body(monkeypatch, profile, messages, **kw):
    import requests

    captured = {}

    class FakeResp:
        status_code = 200

        def json(self):
            return {}

        def iter_lines(self, *a, **k):
            return []

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_post(url, headers=None, json=None, timeout=None, stream=None):
        captured["body"] = json
        return FakeResp()

    monkeypatch.setattr(requests, "post", fake_post)
    from aps.services.adapters.chat_adapter import ChatCompletionsAdapter
    result = ChatCompletionsAdapter().generate(
        profile, "k", system="sys", messages=messages,
        web_search=False, reasoning="high",
        max_tokens=None, temperature=None, **kw)
    assert result is not None
    return captured["body"]


def test_chat_adapter_tool_messages_serialized(monkeypatch):
    from aps.services.adapters.chat_adapter import ChatCompletionsAdapter
    p = AIProfile(profile_id="p1")
    msgs = [ChatMessage(role="user", content="hi"),
            ChatMessage(role="assistant", content="", tool_calls=[
                ToolCall(id="call_9", name="now", arguments="{}")]),
            ChatMessage(role="tool", content='{"ok": true}', tool_call_id="call_9")]
    body = _chat_adapter_body(monkeypatch, p, msgs, tool_defs=[{
        "name": "now", "description": "d", "parameters": {"type": "object"}}])
    assert body["tools"] == [{"type": "function", "function": {
        "name": "now", "description": "d", "parameters": {"type": "object"}}}]
    ms = body["messages"]
    assert ms[0]["role"] == "system"
    assert ms[1]["role"] == "user"
    assert ms[2]["role"] == "assistant"
    assert ms[2]["tool_calls"][0]["function"]["name"] == "now"
    assert ms[2]["tool_calls"][0]["id"] == "call_9"
    assert ms[3]["role"] == "tool"
    assert ms[3]["tool_call_id"] == "call_9"
    assert ms[3]["content"] == '{"ok": true}'


def test_responses_adapter_tool_messages_serialized(monkeypatch):
    import requests

    captured = {}

    class FakeResp:
        status_code = 200

        def json(self):
            return {}

        def iter_lines(self, *a, **k):
            return []

    def fake_post(url, headers=None, json=None, timeout=None, stream=None):
        captured["body"] = json
        return FakeResp()

    monkeypatch.setattr(requests, "post", fake_post)
    from aps.services.adapters.responses_adapter import ResponsesAdapter
    p = AIProfile(profile_id="p1")
    msgs = [ChatMessage(role="user", content="hi"),
            ChatMessage(role="assistant", content="", tool_calls=[
                ToolCall(id="call_9", name="now", arguments="{}")]),
            ChatMessage(role="tool", content='{"ok": true}', tool_call_id="call_9")]
    ResponsesAdapter().generate(
        p, "k", system="sys", messages=msgs, web_search=False,
        reasoning="high", max_tokens=None, temperature=None,
        tool_defs=[{"name": "now", "description": "d",
                    "parameters": {"type": "object"}}])
    body = captured["body"]
    assert body["tools"] == [{"type": "function", "name": "now",
                              "description": "d", "parameters": {"type": "object"}}]
    items = body["input"]
    assert items[0] == {"role": "user",
                        "content": [{"type": "input_text", "text": "hi"}]}
    assert items[1]["role"] == "assistant"
    assert items[1]["output"][0]["type"] == "function_call"
    assert items[1]["output"][0]["call_id"] == "call_9"
    assert items[1]["output"][0]["name"] == "now"
    assert items[2] == {"type": "function_call_output",
                        "call_id": "call_9", "output": '{"ok": true}'}


def test_web_search_and_tools_combined_responses(monkeypatch):
    import requests

    captured = {}

    class FakeResp:
        status_code = 200

        def json(self):
            return {}

        def iter_lines(self, *a, **k):
            return []

    def fake_post(url, headers=None, json=None, timeout=None, stream=None):
        captured["body"] = json
        return FakeResp()

    monkeypatch.setattr(requests, "post", fake_post)
    from aps.services.adapters.responses_adapter import ResponsesAdapter
    p = AIProfile(profile_id="p1")
    ResponsesAdapter().generate(
        p, "k", system="sys", messages=[ChatMessage(role="user", content="q")],
        web_search=True, reasoning="high", max_tokens=None, temperature=None,
        tool_defs=[{"name": "now", "description": "d",
                    "parameters": {"type": "object"}}])
    tools = captured["body"]["tools"]
    assert {"type": "web_search"} in tools
    assert {"type": "function", "name": "now", "description": "d",
            "parameters": {"type": "object"}} in tools

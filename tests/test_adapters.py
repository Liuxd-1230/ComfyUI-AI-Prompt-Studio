"""Adapter 测试：mock requests，不触网。

覆盖：正常流式 / reasoning / tool_calls / citations / usage /
错误归一化（401 不降级、429、5xx）/ 协议不支持判定 / 超时 / 连接失败 / 取消。
"""
import json
import threading

import pytest
import requests

from aps.schemas.profile import AIProfile
from aps.schemas.results import ChatMessage
from aps.services.adapters.base import ProtocolUnsupported
from aps.services.adapters.chat_adapter import ChatCompletionsAdapter
from aps.services.adapters.responses_adapter import ResponsesAdapter


class FakeResponse:
    def __init__(self, status_code=200, text="", lines=None):
        self.status_code = status_code
        self.text = text
        self._lines = list(lines or [])

    def iter_lines(self, decode_unicode=True):
        return iter(self._lines)

    def close(self):
        pass


def sse(payloads):
    """把 dict 列表包装成 SSE 行（data + 空行分隔）。"""
    lines = []
    for p in payloads:
        lines.append("data: " + json.dumps(p))
        lines.append("")
    return lines


def make_post_fake(monkeypatch, lines=None, status=200, text="", exc=None):
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None, stream=None):
        calls.append({"url": url, "headers": headers, "json": json,
                      "timeout": timeout})
        if exc is not None:
            raise exc
        return FakeResponse(status_code=status, text=text, lines=lines)

    monkeypatch.setattr(requests, "post", fake_post)
    return calls


def profile(**kw):
    kw.setdefault("provider", "deepseek")
    return AIProfile(profile_id="p1", **kw)


# ------------------------------------------------------------------ Responses

def test_responses_stream_text_reasoning_usage(monkeypatch):
    events = [
        {"type": "response.output_text.delta", "delta": "你好"},
        {"type": "response.output_text.delta", "delta": "，世界"},
        {"type": "response.reasoning_summary_text.delta", "delta": "思考中"},
        {"type": "response.completed",
         "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
                   "input_tokens_details": {"cached_tokens": 3},
                   "output_tokens_details": {"reasoning_tokens": 2}}},
    ]
    calls = make_post_fake(monkeypatch, lines=sse(events))
    result = ResponsesAdapter().generate(profile(), "sk", system="sys",
                                         messages=[], web_search=False,
                                         reasoning="high", max_tokens=100,
                                         temperature=1.0)
    assert result.text == "你好，世界"
    assert result.reasoning == "思考中"
    assert result.usage.input_tokens == 10
    assert result.usage.reasoning_tokens == 2
    assert result.usage.prompt_cache_hit_tokens == 3
    assert result.protocol == "responses"
    assert calls[0]["url"] == "https://api.deepseek.com/responses"
    body = calls[0]["json"]
    assert body["reasoning"] == {"effort": "high"}
    assert body["tools"] == []


def test_responses_native_web_search_tool_and_citations(monkeypatch):
    events = [
        {"type": "response.output_item.done",
         "item": {"type": "web_search_call", "output": [
             {"type": "web_search", "url": "https://example.com/a",
              "title": "A"}]}},
        {"type": "response.output_text.delta", "delta": "结论"},
    ]
    make_post_fake(monkeypatch, lines=sse(events))
    result = ResponsesAdapter().generate(profile(), "sk", system="",
                                         messages=[], web_search=True,
                                         reasoning="off", max_tokens=100,
                                         temperature=0.7)
    assert len(result.citations) == 1
    assert result.citations[0].url == "https://example.com/a"
    assert result.text == "结论"


def test_responses_function_tool_call(monkeypatch):
    events = [
        {"type": "response.function_call_arguments.delta", "delta": "{\"q\":"},
        {"type": "response.function_call_arguments.delta", "delta": "\"test\"}"},
        {"type": "response.output_item.done",
         "item": {"type": "function_call", "name": "web_search",
                  "arguments": "{\"q\": \"test\"}"}},
    ]
    make_post_fake(monkeypatch, lines=sse(events))
    result = ResponsesAdapter().generate(profile(), "sk", system="",
                                         messages=[], web_search=False,
                                         reasoning="low", max_tokens=100,
                                         temperature=1.0)
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "web_search"
    assert '"q"' in result.tool_calls[0].arguments


def test_responses_messages_input_mapping(monkeypatch):
    calls = make_post_fake(monkeypatch, lines=sse([]))
    msgs = [ChatMessage(role="user", content="hi"),
            ChatMessage(role="assistant", content="hello")]
    ResponsesAdapter().generate(profile(), "sk", system="sys", messages=msgs,
                                web_search=False, reasoning="off",
                                max_tokens=100, temperature=1.0)
    body = calls[0]["json"]
    assert body["input"][0]["content"][0]["text"] == "hi"
    assert body["input"][1]["role"] == "assistant"
    assert "reasoning" not in body  # off 不发送 reasoning


def test_responses_http_error_mapping(monkeypatch):
    for status, kind in [(401, "auth_error"), (402, "insufficient_balance"),
                         (429, "rate_limit"), (500, "server_error")]:
        make_post_fake(monkeypatch, status=status, text="err")
        result = ResponsesAdapter().generate(profile(), "bad", system="",
                                             messages=[], web_search=False,
                                             reasoning="high", max_tokens=100,
                                             temperature=1.0)
        assert result.has_error()
        assert result.error.kind == kind, f"status {status} -> {kind}"
        assert result.error.http_status == status


def test_responses_protocol_unsupported_raises(monkeypatch):
    make_post_fake(monkeypatch, status=404, text="no such endpoint")
    with pytest.raises(ProtocolUnsupported):
        ResponsesAdapter().generate(profile(), "sk", system="", messages=[],
                                    web_search=False, reasoning="high",
                                    max_tokens=100, temperature=1.0)


def test_responses_unknown_param_400_raises(monkeypatch):
    make_post_fake(monkeypatch, status=400,
                   text='{"error": {"message": "Unknown parameter: reasoning"}}')
    with pytest.raises(ProtocolUnsupported):
        ResponsesAdapter().generate(profile(), "sk", system="", messages=[],
                                    web_search=False, reasoning="high",
                                    max_tokens=100, temperature=1.0)


def test_responses_timeout(monkeypatch):
    make_post_fake(monkeypatch, exc=requests.Timeout())
    result = ResponsesAdapter().generate(profile(), "sk", system="", messages=[],
                                         web_search=False, reasoning="high",
                                         max_tokens=100, temperature=1.0)
    assert result.error.kind == "timeout"


def test_responses_connection_error(monkeypatch):
    make_post_fake(monkeypatch, exc=requests.ConnectionError("down"))
    result = ResponsesAdapter().generate(profile(), "sk", system="", messages=[],
                                         web_search=False, reasoning="high",
                                         max_tokens=100, temperature=1.0)
    assert result.error.kind == "network_error"


def test_responses_cancel(monkeypatch):
    make_post_fake(monkeypatch, lines=sse([{"type": "response.output_text.delta",
                                            "delta": "x"}]))
    ev = threading.Event()
    ev.set()
    result = ResponsesAdapter().generate(profile(), "sk", system="", messages=[],
                                         web_search=False, reasoning="high",
                                         max_tokens=100, temperature=1.0,
                                         stop_event=ev)
    assert result.error.kind == "canceled"


# ------------------------------------------------------------------ Chat

def test_chat_stream_text_reasoning_usage(monkeypatch):
    events = [
        {"choices": [{"delta": {"content": "你好"}}]},
        {"choices": [{"delta": {"content": "，世界"}}]},
        {"choices": [{"delta": {"reasoning_content": "想好了"}}]},
        {"choices": [], "usage": {"prompt_tokens": 8, "completion_tokens": 4,
                                   "total_tokens": 12,
                                   "prompt_cache_hit_tokens": 2}},
    ]
    calls = make_post_fake(monkeypatch, lines=sse(events))
    result = ChatCompletionsAdapter().generate(profile(), "sk", system="sys",
                                               messages=[ChatMessage(role="user",
                                                                     content="hi")],
                                               web_search=False, reasoning="high",
                                               max_tokens=100, temperature=1.0)
    assert result.text == "你好，世界"
    assert result.reasoning == "想好了"
    assert result.usage.input_tokens == 8
    assert calls[0]["url"] == "https://api.deepseek.com/chat/completions"
    body = calls[0]["json"]
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    assert body["reasoning_effort"] == "high"
    assert body["stream"] is True


def test_chat_tool_calls_delta_accumulation(monkeypatch):
    events = [
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_1",
             "function": {"name": "web", "arguments": "{\"q\":"}}]}}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": "\"x\"}"}}]}}]},
    ]
    make_post_fake(monkeypatch, lines=sse(events))
    result = ChatCompletionsAdapter().generate(profile(), "sk", system="",
                                               messages=[], web_search=False,
                                               reasoning="off", max_tokens=100,
                                               temperature=1.0)
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "web"
    assert result.tool_calls[0].arguments == '{"q":"x"}'
    assert result.tool_calls[0].id == "call_1"


def test_chat_generic_endpoint_no_deepseek_params(monkeypatch):
    """通用 OpenAI 兼容端点：不发送 reasoning_effort / response_format。"""
    calls = make_post_fake(monkeypatch, lines=sse([]))
    p = profile(provider="openai_compatible", base_url="http://localhost:8000/v1")
    ChatCompletionsAdapter().generate(p, "k", system="", messages=[],
                                      web_search=False, reasoning="high",
                                      max_tokens=100, temperature=1.0,
                                      json_mode=True)
    body = calls[0]["json"]
    assert "reasoning_effort" not in body
    assert "response_format" not in body
    assert calls[0]["url"] == "http://localhost:8000/v1/chat/completions"


def test_chat_http_error(monkeypatch):
    make_post_fake(monkeypatch, status=429, text="slow down")
    result = ChatCompletionsAdapter().generate(profile(), "k", system="",
                                               messages=[], web_search=False,
                                               reasoning="high", max_tokens=100,
                                               temperature=1.0)
    assert result.error.kind == "rate_limit"

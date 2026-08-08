"""OpenAI 兼容 Chat Completions 适配器（POST {base}/chat/completions）。

适用于：DeepSeek /chat/completions、OpenAI 兼容端点、本地运行时
（Ollama / llama.cpp / LM Studio 均提供该接口）。
支持：流式（SSE）、reasoning_content（DeepSeek）、function tool 调用（delta 累积）、usage。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import requests

from ...schemas.profile import AIProfile
from ...schemas.results import Citation, LLMResult, ToolCall, Usage, make_error
from .base import (
    Canceled,
    ProtocolUnsupported,
    accumulate_usage,
    is_protocol_unsupported,
    map_http_error,
    sse_events,
)

logger = logging.getLogger("ai_prompt_studio.adapters.chat")

REASONING_EFFORT = {"off": "none", "low": "low", "medium": "medium", "high": "high"}


class _ChatConsumer:
    """从 SSE 事件流中累积 Chat Completions 的输出。"""

    def __init__(self, profile: AIProfile):
        self.profile = profile
        self.text_parts: List[str] = []
        self.reasoning_parts: List[str] = []
        self.tool_calls: List[ToolCall] = []
        self._tool_calls_by_index: Dict[int, ToolCall] = {}
        self.usage: Dict[str, Any] = {}

    def feed(self, event: Dict[str, Any]) -> None:
        choices = event.get("choices") or []
        if not isinstance(choices, list) or not choices:
            accumulate_usage(event, self.usage)
            return
        delta = choices[0].get("delta") or {}
        if not isinstance(delta, dict):
            return
        content = delta.get("content")
        if isinstance(content, str) and content:
            self.text_parts.append(content)
        reasoning = delta.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning:
            self.reasoning_parts.append(reasoning)
        for tc in delta.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            idx = tc.get("index", 0)
            entry = self._tool_calls_by_index.setdefault(
                idx, ToolCall(name="", arguments=""))
            fn = tc.get("function") or {}
            if isinstance(fn, dict):
                if fn.get("name"):
                    entry.name += fn["name"]
                if fn.get("arguments"):
                    entry.arguments += fn["arguments"]
            if tc.get("id"):
                entry.id = tc["id"]
        if choices[0].get("finish_reason"):
            accumulate_usage(event, self.usage)

    def finalize(self) -> LLMResult:
        result = LLMResult(profile_id=self.profile.profile_id, model=self.profile.model,
                           protocol="chat_completions")
        result.text = "".join(self.text_parts)
        result.reasoning = "".join(self.reasoning_parts)
        result.tool_calls = [self._tool_calls_by_index[i]
                             for i in sorted(self._tool_calls_by_index)]
        result.usage = Usage(input_tokens=self.usage.get("input_tokens", 0),
                             output_tokens=self.usage.get("output_tokens", 0),
                             total_tokens=self.usage.get("total_tokens", 0),
                             prompt_cache_hit_tokens=self.usage.get("prompt_cache_hit_tokens", 0),
                             prompt_cache_miss_tokens=self.usage.get("prompt_cache_miss_tokens", 0),
                             reasoning_tokens=self.usage.get("reasoning_tokens", 0),
                             extra=self.usage.get("extra", {}))
        return result


class ChatCompletionsAdapter:
    """OpenAI 兼容 Chat Completions 协议适配器。"""

    protocol = "chat_completions"

    def generate(
        self,
        profile: AIProfile,
        api_key: str,
        *,
        system: str,
        messages: List,
        web_search: bool,
        reasoning: str,
        max_tokens: Optional[int],
        temperature: Optional[float],
        top_p: Optional[float] = None,
        frequency_penalty: Optional[float] = None,
        presence_penalty: Optional[float] = None,
        json_mode: bool = False,
        attachments: Optional[List] = None,
        output_schema: Optional[Dict[str, Any]] = None,
        tool_defs: Optional[List[Dict[str, Any]]] = None,
        stop_event: Optional[Any] = None,
        timeout: float = 120.0,
    ) -> LLMResult:
        base = (profile.base_url or "https://api.deepseek.com").rstrip("/")
        url = f"{base}/chat/completions"

        api_messages: List[Dict[str, Any]] = []
        if system:
            api_messages.append({"role": "system", "content": system})
        for m in messages:
            if m.role == "tool":
                api_messages.append({"role": "tool",
                                     "tool_call_id": m.tool_call_id or "",
                                     "content": m.content})
                continue
            if m.role == "assistant" and m.tool_calls:
                api_messages.append({"role": "assistant",
                                     "content": m.content or None,
                                     "tool_calls": [
                                         {"id": tc.id or f"call_{i}",
                                          "type": "function",
                                          "function": {"name": tc.name,
                                                       "arguments": tc.arguments}}
                                         for i, tc in enumerate(m.tool_calls)]})
                continue
            if not m.content:
                continue
            api_messages.append({"role": m.role, "content": m.content})

        # 附件并入最后一条 user 消息（多模态 content parts：图片 image_url / 文件 file）
        if attachments:
            parts = _attachment_parts(attachments)
            if parts:
                if api_messages and api_messages[-1]["role"] == "user":
                    api_messages[-1]["content"] = _to_parts(api_messages[-1]["content"]) + parts
                else:
                    api_messages.append({"role": "user", "content": parts})

        body: Dict[str, Any] = {
            "model": profile.model,
            "messages": api_messages,
            "stream": True,
        }
        # 函数工具（OpenAI 兼容 tools 数组）
        if tool_defs:
            body["tools"] = [{"type": "function", "function": td}
                             for td in tool_defs]
        # 采样参数 None = 不发送，交给 provider 默认值（档案高级设置才可配置）
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if temperature is not None:
            body["temperature"] = temperature
        if top_p is not None:
            body["top_p"] = top_p
        if frequency_penalty is not None:
            body["frequency_penalty"] = frequency_penalty
        if presence_penalty is not None:
            body["presence_penalty"] = presence_penalty
        # reasoning_effort / response_format 是 DeepSeek 特有参数；通用端点可能 400，只对 deepseek 发送
        if reasoning != "off" and profile.provider == "deepseek":
            body["reasoning_effort"] = REASONING_EFFORT.get(reasoning, "high")
        if json_mode and profile.provider == "deepseek":
            body["response_format"] = {"type": "json_object"}
        # 结构化输出：response_format json_schema（OpenAI 兼容端点官方结构）
        if output_schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "structured_output", "schema": output_schema, "strict": True}}

        headers = {"Authorization": f"Bearer {api_key}",
                   "Content-Type": "application/json"}

        resp = None
        try:
            resp = requests.post(url, headers=headers, json=body,
                                 timeout=(10.0, timeout), stream=True)
        except requests.Timeout:
            return LLMResult(profile_id=profile.profile_id, model=profile.model,
                             protocol=self.protocol,
                             error=make_error("timeout", "读取超时"))
        except requests.RequestException as exc:
            return LLMResult(profile_id=profile.profile_id, model=profile.model,
                             protocol=self.protocol,
                             error=make_error("network_error",
                                              f"无法连接 {url}：{exc.__class__.__name__}"))

        try:
            if resp.status_code != 200:
                body_text = _safe_body(resp)
                if is_protocol_unsupported(resp.status_code, body_text):
                    raise ProtocolUnsupported(
                        f"Chat Completions 不可用 HTTP {resp.status_code}：{body_text[:120]}",
                        http_status=resp.status_code)
                return LLMResult(profile_id=profile.profile_id, model=profile.model,
                                 protocol=self.protocol,
                                 error=map_http_error(resp.status_code, body_text[:200]))
            consumer = _ChatConsumer(profile)
            try:
                for event in sse_events(resp):
                    if stop_event is not None and stop_event.is_set():
                        raise Canceled()
                    consumer.feed(event)
            except Canceled:
                return LLMResult(profile_id=profile.profile_id, model=profile.model,
                                 protocol=self.protocol,
                                 error=make_error("canceled", "已取消"))
            return consumer.finalize()
        finally:
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass


def _safe_body(resp) -> str:
    try:
        return resp.text[:1000]
    except Exception:  # noqa: BLE001
        return ""


def _to_parts(content) -> List[Dict[str, Any]]:
    """把纯文本 user content 转成 content parts 数组（纯文本原样返回）。"""
    if isinstance(content, list):
        return content
    return [{"type": "text", "text": str(content)}]


def _attachment_parts(attachments) -> List[Dict[str, Any]]:
    """附件 → Chat Completions content parts（官方结构，2026-08-07 查证）：
    - 图片：{"type": "image_url", "image_url": {"url": data_uri}}
    - 文件：{"type": "file", "file": {"file_data": ..., "filename": ...}}
    - 文本：{"type": "text", "text": ...}
    """
    parts: List[Dict[str, Any]] = []
    for a in attachments or []:
        if a.kind == "text":
            parts.append({"type": "text", "text": a.content})
        elif a.kind == "image":
            parts.append({"type": "image_url",
                          "image_url": {"url": a.as_data_uri()}})
        elif a.kind == "file":
            parts.append({"type": "file", "file": {
                "file_data": a.content.split(",", 1)[-1],
                "filename": a.name or "attachment.bin"}})
    return parts

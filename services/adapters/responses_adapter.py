"""DeepSeek Responses API 适配器（POST {base}/responses）。

支持：流式（SSE）、reasoning（off/low/medium/high）、原生 web_search 工具、
function tool 调用、citations（web_search 输出容错提取）、usage。
事件解析对 DeepSeek 事件名差异宽容（_event 或 body.type 均可）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests

from ...schemas.profile import AIProfile
from ...schemas.results import Citation, LLMResult, ToolCall, Usage, make_error
from .base import (
    Canceled,
    ProtocolUnsupported,
    accumulate_usage,
    deep_find_urls,
    is_protocol_unsupported,
    map_http_error,
    sse_events,
)

logger = logging.getLogger("ai_prompt_studio.adapters.responses")

REASONING_EFFORT = {"off": "none", "low": "low", "medium": "medium", "high": "high"}


class _StreamConsumer:
    """从 SSE 事件流中累积 Responses 协议的输出。"""

    def __init__(self, profile: AIProfile):
        self.profile = profile
        self.text_parts: List[str] = []
        self.reasoning_parts: List[str] = []
        self.tool_calls: List[ToolCall] = []
        self._tool_name = ""
        self._tool_args = ""
        self.citations: List[Citation] = []
        self._urls = set()
        self.usage: Dict[str, Any] = {}
        self.failed = False
        self.server_error = ""

    def feed(self, event: Dict[str, Any]) -> None:
        kind = event.get("_event") or event.get("type") or ""
        data = event.get("delta") or event.get("text") or event.get("output_text_delta") or ""

        if "output_text.delta" in kind and isinstance(data, str):
            self.text_parts.append(data)
        elif kind == "response.output_text.done" and isinstance(data, str) and not self.text_parts:
            self.text_parts.append(data)
        elif "reasoning_summary_text.delta" in kind or "reasoning_text.delta" in kind:
            if isinstance(data, str):
                self.reasoning_parts.append(data)
        elif "function_call_arguments.delta" in kind and isinstance(data, str):
            self._tool_args += data
        elif "function_call.name.delta" in kind and isinstance(data, str):
            self._tool_name += data
        elif kind == "response.output_item.done":
            self._on_item(event.get("item") or {})
        elif kind == "response.completed":
            accumulate_usage(event, self.usage)
        elif kind == "response.failed":
            self.failed = True
            err = event.get("error") or {}
            if isinstance(err, dict):
                self.server_error = str(err.get("message", err))
            else:
                self.server_error = str(err)

    def _on_item(self, item: Dict[str, Any]) -> None:
        if not isinstance(item, dict):
            return
        itype = item.get("type", "")
        if itype == "message":
            for part in item.get("content") or []:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    self.text_parts.append(part["text"])
        elif itype == "reasoning":
            for part in item.get("content") or []:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    self.reasoning_parts.append(part["text"])
        elif itype == "function_call":
            name = item.get("name") or self._tool_name
            args = item.get("arguments") or self._tool_args
            if name:
                self.tool_calls.append(ToolCall(name=name, arguments=args))
                self._tool_name, self._tool_args = "", ""
        elif itype == "web_search_call":
            deep_find_urls(item.get("output") or item, self._urls)

    def finalize(self) -> LLMResult:
        result = LLMResult(profile_id=self.profile.profile_id, model=self.profile.model,
                           protocol="responses")
        result.text = "".join(self.text_parts)
        result.reasoning = "".join(self.reasoning_parts)
        result.tool_calls = self.tool_calls
        for u in sorted(self._urls):
            result.citations.append(Citation(index=len(result.citations), url=u))
        result.usage = Usage(input_tokens=self.usage.get("input_tokens", 0),
                             output_tokens=self.usage.get("output_tokens", 0),
                             total_tokens=self.usage.get("total_tokens", 0),
                             prompt_cache_hit_tokens=self.usage.get("prompt_cache_hit_tokens", 0),
                             prompt_cache_miss_tokens=self.usage.get("prompt_cache_miss_tokens", 0),
                             reasoning_tokens=self.usage.get("reasoning_tokens", 0),
                             extra=self.usage.get("extra", {}))
        if self.failed:
            result.error = make_error(
                "server_error", self.server_error or "响应流以失败事件结束")
        return result


class ResponsesAdapter:
    """DeepSeek Responses 协议适配器。"""

    protocol = "responses"

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
        attachments: Optional[List] = None,
        output_schema: Optional[Dict[str, Any]] = None,
        stop_event: Optional[Any] = None,
        timeout: float = 120.0,
    ) -> LLMResult:
        base = (profile.base_url or "https://api.deepseek.com").rstrip("/")
        url = f"{base}/responses"

        tools = [{"type": "web_search"}] if web_search else []
        body: Dict[str, Any] = {
            "model": profile.model,
            "instructions": system or "You are a helpful assistant.",
            "input": _input_from_messages(messages) + _attachment_input_items(attachments),
            "tools": tools,
            "stream": True,
        }
        # 结构化输出：text.format json_schema（OpenAI Responses 官方结构）
        if output_schema:
            body["text"] = {"format": {
                "type": "json_schema", "name": "structured_output",
                "schema": output_schema, "strict": True}}
        # 采样参数 None = 不发送，交给 provider 默认值（档案高级设置才可配置）
        if max_tokens is not None:
            body["max_output_tokens"] = max_tokens
        if temperature is not None:
            body["temperature"] = temperature
        if reasoning != "off":
            body["reasoning"] = {"effort": REASONING_EFFORT.get(reasoning, "high")}

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
                        f"Responses 接口不可用 HTTP {resp.status_code}：{body_text[:120]}",
                        http_status=resp.status_code)
                return LLMResult(profile_id=profile.profile_id, model=profile.model,
                                 protocol=self.protocol,
                                 error=map_http_error(resp.status_code, body_text[:200]))
            consumer = _StreamConsumer(profile)
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


def _input_from_messages(messages) -> List[Dict[str, Any]]:
    """ChatMessage 列表 → Responses input 数组（content 只接受纯文本）。"""
    result = []
    for m in messages:
        if not m.content:
            continue
        result.append({"role": m.role,
                       "content": [{"type": "input_text", "text": m.content}]})
    return result


def _attachment_input_items(attachments) -> List[Dict[str, Any]]:
    """附件 → Responses input 条目（官方：input_image / input_file content parts）。

    官方结构（api-docs.deepseek.com，2026-08-07 查证）：
    - 图片：content part {"type": "input_image", "image_url": data_uri, "filename": ...}
    - 文件：content part {"type": "input_file", "file_data": ..., "filename": ...}
      （file_data/file_id/file_url 三选一）
    - 文本：直接并入已有 user 消息，不新增条目
    """
    items: List[Dict[str, Any]] = []
    for a in attachments or []:
        if a.kind == "text":
            # 文本附件作为独立 user 消息条目（保持顺序可读）
            items.append({"role": "user", "content": [
                {"type": "input_text", "text": a.content}]})
        elif a.kind == "image":
            items.append({"role": "user", "content": [
                {"type": "input_image", "image_url": a.as_data_uri(),
                 "filename": a.name or "image.png"}]})
        elif a.kind == "file":
            items.append({"role": "user", "content": [
                {"type": "input_file",
                 "file_data": a.content.split(",", 1)[-1],
                 "filename": a.name or "attachment.bin"}]})
    return items


def _safe_body(resp) -> str:
    try:
        return resp.text[:1000]
    except Exception:  # noqa: BLE001
        return ""

"""DeepSeek Responses API 适配器（POST {base}/responses）。

支持：流式（SSE）、reasoning（off/low/medium/high）、原生 web_search 工具、
function tool 调用、citations（web_search 输出容错提取）、usage。
事件解析对 DeepSeek 事件名差异宽容（_event 或 body.type 均可）。
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
    deep_find_urls,
    is_protocol_unsupported,
    map_http_error,
    sse_events,
)

logger = logging.getLogger("ai_prompt_studio.adapters.responses")

REASONING_EFFORT = {"off": "none", "low": "low", "medium": "medium", "high": "high"}


class _StreamConsumer:
    """从 SSE 事件流中累积 Responses 协议的输出。

    function call 关联（官方结构，2026-08-07 查证，docs/research.md §7）：
    - 流式 function_call_arguments.delta/done 事件携带 item_id + output_index（不是 call_id）；
    - call_id 只出现在 function_call 输出项（output[] 与 response.output_item.done 的 item）里；
    - 因此参数 delta 按 item_id 累积，call_id 在 function_call 项到达时取权威值。
    """

    def __init__(self, profile: AIProfile):
        self.profile = profile
        self.text_parts: List[str] = []
        self.reasoning_parts: List[str] = []
        self.tool_calls: List[ToolCall] = []
        # 按 item_id（或 output_index）累积 function call 参数；并行调用互不干扰
        self._tool_parts: Dict[str, Dict[str, str]] = {}
        self._tool_order: List[str] = []
        self.citations: List[Citation] = []
        self._urls = set()
        self.usage: Dict[str, Any] = {}
        self.failed = False
        self.server_error = ""

    def _part(self, key: str) -> Dict[str, str]:
        """取（或新建）某个 item_id 的累积槽；空 key 用临时槽。"""
        key = (key or "").strip() or "__slot__"
        if key not in self._tool_parts:
            self._tool_parts[key] = {"name": "", "args": ""}
            self._tool_order.append(key)
        return self._tool_parts[key]

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
            # 官方：delta 事件用 item_id 标识目标 function call（非 call_id）
            key = (event.get("item_id") or event.get("output_index") or "") if (
                event.get("item_id") or event.get("output_index") is not None) else ""
            self._part(str(key))["args"] += data
        elif kind == "response.function_call_arguments.done":
            key = str(event.get("item_id") or event.get("output_index") or "") if (
                event.get("item_id") or event.get("output_index") is not None) else ""
            if isinstance(data, str):
                part = self._part(key)
                part["args"] = data
                if isinstance(event.get("name"), str) and event["name"]:
                    part["name"] = event["name"]
        elif "function_call.name.delta" in kind and isinstance(data, str):
            self._part(str(event.get("item_id") or ""))["name"] += data
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
            # 官方结构：{"type":"function_call","call_id":...,"id":...,"name":...,"arguments":...}
            cid = (item.get("call_id") or "").strip()
            # 优先按 item.id（=流式 item_id）取累积的参数
            iid = (item.get("id") or "").strip()
            part = self._tool_parts.pop(iid, None)
            if part is None and cid and cid in self._tool_parts:
                part = self._tool_parts.pop(cid, None)
            if part is None and self._tool_parts:
                part = self._tool_parts.pop(self._tool_order[0], None)
            name = item.get("name") or (part or {}).get("name", "")
            args = item.get("arguments")
            if not isinstance(args, str):
                args = json.dumps(args, ensure_ascii=False) if args is not None else ""
            args = args or (part or {}).get("args", "")
            if name:
                self.tool_calls.append(ToolCall(id=cid, name=name, arguments=args))
        elif itype == "web_search_call":
            deep_find_urls(item.get("output") or item, self._urls)

    def finalize(self) -> LLMResult:
        # 兜底：只有 delta、没有 item.done 的 function call 在此落盘（避免丢失）
        for key in list(self._tool_parts.keys()):
            part = self._tool_parts.pop(key)
            if part.get("name"):
                self.tool_calls.append(ToolCall(name=part["name"],
                                                arguments=part["args"]))
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
        tool_defs: Optional[List[Dict[str, Any]]] = None,
        stop_event: Optional[Any] = None,
        timeout: float = 120.0,
    ) -> LLMResult:
        base = (profile.base_url or "https://api.deepseek.com").rstrip("/")
        url = f"{base}/responses"

        tools: List[Dict[str, Any]] = []
        if web_search:
            tools.append({"type": "web_search"})
        for td in tool_defs or []:
            tools.append({"type": "function", **td})
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
    """ChatMessage 列表 → Responses input 数组（工具续轮按官方结构编码）。

    官方结构（api-docs.deepseek.com，2026-08-07 查证）：
    - 助手消息携带 function_call：{"role": "assistant", "output":
      [{"type": "function_call", "call_id": ..., "name": ..., "arguments": ...}]}
    - 工具结果：{"type": "function_call_output", "call_id": ..., "output": ...}
    - 普通消息：content 只接受纯文本 input_text part
    """
    result = []
    for m in messages:
        if m.role == "tool":
            result.append({"type": "function_call_output",
                           "call_id": m.tool_call_id or "",
                           "output": m.content})
            continue
        if m.role == "assistant" and m.tool_calls:
            item: Dict[str, Any] = {"role": "assistant",
                                    "content": [{"type": "input_text",
                                                 "text": m.content}]
                                    if m.content else []}
            # call_id 必须逐字沿用模型返回的真实 ID（0.2.1 P0-7）；
            # 缺失时为协议错误，由 Provider 显式拒绝，绝不临时伪造 call_N
            item["output"] = [{"type": "function_call",
                               "call_id": tc.id,
                               "name": tc.name,
                               "arguments": tc.arguments}
                              for tc in m.tool_calls]
            result.append(item)
            continue
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

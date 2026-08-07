"""Adapter 公共部分：SSE 解析、HTTP 错误归一化、协议不支持判定。

原则（docs/decisions.md D6/D7）：
- 401/402/403/429/5xx/网络失败绝不静默降级 → 归一化为结构化 ErrorInfo；
- 只有「接口/参数不支持」（protocol_unsupported）允许降级链处理；
- text 永远只承载模型回答，错误放 error 字段（LLMResult）。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, List, Optional

from ...schemas.results import ErrorInfo, make_error

logger = logging.getLogger("ai_prompt_studio.adapters")


class ProtocolUnsupported(Exception):
    """接口/参数不支持（可降级）。携带原始 HTTP 状态与错误摘要。"""

    def __init__(self, message: str, http_status: int = 0):
        super().__init__(message)
        self.http_status = http_status


class Canceled(Exception):
    """用户取消（stop_event 触发）。"""


def map_http_error(status: int, detail: str = "") -> ErrorInfo:
    """按 HTTP 状态码归一化错误（错误 body 官方未公开，只按状态码判断）。"""
    if status == 401:
        kind = "auth_error"
    elif status == 402:
        kind = "insufficient_balance"
    elif status == 403:
        kind = "forbidden"
    elif status == 429:
        kind = "rate_limit"
    elif status in (400, 422):
        kind = "invalid_request"
    elif status >= 500:
        kind = "server_error"
    else:
        kind = "invalid_request"
    message = detail or f"HTTP {status}"
    return make_error(kind, message, http_status=status)


def is_protocol_unsupported(status: int, body_text: str = "") -> bool:
    """判断失败是否属于「协议/参数不支持」（可降级）。"""
    if status in (404, 405):
        return True
    if status == 400:
        hints = (
            "unknown parameter", "unknown argument", "not supported",
            "unsupported", "unknown tool", "does not support",
            "invalid 'reasoning'", "reasoning", "未知参数", "不支持",
        )
        low = (body_text or "").lower()
        return any(h in low for h in hints)
    return False


def sse_events(resp: Any) -> Iterable[Dict[str, Any]]:
    """把 requests.Response 的 iter_lines() 解析为 SSE 事件 dict。

    容忍：无 event 行的纯 data 流、非 JSON data、多行 data 拼接、[DONE] 哨兵。
    事件名优先取 `_event`（显式 event: 行），否则用 body 内 type 字段。
    """
    buffer: List[str] = []
    event_name: Optional[str] = None

    def flush():
        if not buffer:
            return None
        data = "\n".join(buffer)
        buffer.clear()
        if data.strip() == "[DONE]":
            return None
        try:
            payload = json.loads(data)
        except ValueError:
            logger.warning("SSE 非 JSON data: %s", data[:200])
            return None
        if event_name:
            payload.setdefault("_event", event_name)
        return payload

    for raw in resp.iter_lines(decode_unicode=True):
        if raw is None:
            continue
        line = raw.strip()
        if not line:
            payload = flush()
            event_name = None
            if payload:
                yield payload
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[len("event:"):].strip()
            continue
        if line.startswith("data:"):
            buffer.append(line[len("data:"):].strip())
            continue
        # 其他字段（id/retry）忽略
    payload = flush()
    if payload:
        yield payload


def accumulate_usage(data: Dict[str, Any], usage: Dict[str, Any]) -> None:
    """把协议各自的 usage 字段合并进统一 dict（idempotent）。

    Responses: input_tokens/output_tokens/total_tokens + *_details；
    Chat Completions: prompt_tokens/completion_tokens + 缓存字段。
    """
    u = data.get("usage") or {}
    if not isinstance(u, dict):
        return
    # Chat Completions 命名
    usage["input_tokens"] = u.get("input_tokens", u.get("prompt_tokens", usage.get("input_tokens", 0)))
    usage["output_tokens"] = u.get("output_tokens", u.get("completion_tokens", usage.get("output_tokens", 0)))
    usage["total_tokens"] = u.get("total_tokens", usage.get("total_tokens", 0))
    details = u.get("input_tokens_details") or {}
    if isinstance(details, dict):
        usage["prompt_cache_hit_tokens"] = details.get(
            "cached_tokens", usage.get("prompt_cache_hit_tokens", 0))
    out_details = u.get("output_tokens_details") or {}
    if isinstance(out_details, dict):
        usage["reasoning_tokens"] = out_details.get(
            "reasoning_tokens", usage.get("reasoning_tokens", 0))
    # Chat Completions 的 usage 直接带缓存字段
    usage["prompt_cache_hit_tokens"] = u.get(
        "prompt_cache_hit_tokens", usage.get("prompt_cache_hit_tokens", 0))
    usage["prompt_cache_miss_tokens"] = u.get(
        "prompt_cache_miss_tokens", usage.get("prompt_cache_miss_tokens", 0))
    for k, v in u.items():
        if k not in ("input_tokens", "output_tokens", "total_tokens",
                     "prompt_tokens", "completion_tokens",
                     "input_tokens_details", "output_tokens_details",
                     "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
            usage.setdefault("extra", {})[k] = v


def deep_find_urls(obj: Any, found: set) -> None:
    """递归收集对象中所有 url 字段（citations 容错提取）。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "url" and isinstance(v, str) and v.startswith("http"):
                found.add(v)
            else:
                deep_find_urls(v, found)
    elif isinstance(obj, list):
        for item in obj:
            deep_find_urls(item, found)

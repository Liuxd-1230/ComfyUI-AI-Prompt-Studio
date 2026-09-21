"""联网搜索策略（降级链，docs/decisions.md D7 + P1 外部后端）。

降级链：Responses 原生 web_search → 外部 HTTP 搜索后端（档案 search_url）→
离线 + 明确警告。
- 401/402/403/429/5xx/网络失败绝不降级（由 gateway/adapter 硬失败）；
- 外部后端契约：POST {query} → {"results": [{"title","url","snippet"}]}；
  响应不符合契约 → 明确失败 + 离线警告，不伪造结果。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import requests

from ..schemas.profile import AIProfile

EXTERNAL_TIMEOUT = 15.0


class SearchBackend:
    """外部搜索后端基类（可插拔）。"""

    name = "external"

    def search(self, query: str) -> Dict[str, Any]:
        raise NotImplementedError


def resolve_search_strategy(
    profile: AIProfile,
    capabilities: Dict[str, Any],
    policy: str,
) -> Dict[str, Any]:
    """按联网策略与实测能力返回搜索策略。

    返回 {enabled: bool, native: bool, forced: bool, warning: str, reason: str}

    | 策略 | 原生可用 | 无原生但配了 search_url | 两者都没有 |
    |---|---|---|---|
    | off | 不搜 | 不搜 | 不搜 |
    | auto | 挂 web_search 工具，模型按需调用 | 外部后端注入 | 不搜，不告警 |
    | always | 挂工具并强制 tool_choice | 外部后端注入 | 不搜 + 明确告警 |

    原生能力只认实测 True：未探测（缺键/None）与 False 同样按不支持处理，
    与 gateway 的协议选择同一口径。
    """
    caps = capabilities or {}
    forced = policy == "always"

    if policy == "off":
        return {"enabled": False, "native": False, "forced": False,
                "warning": "", "reason": "policy_off"}

    if caps.get("native_web_search") is True:
        return {"enabled": True, "native": True, "forced": forced,
                "warning": "", "reason": "native"}

    if (profile.search_url or "").strip():
        return {"enabled": True, "native": False, "forced": False,
                "warning": "", "reason": "external"}

    if not forced:
        # auto 是档案默认值：端点没有联网能力时静默不搜，不给每次请求加噪声。
        return {"enabled": False, "native": False, "forced": False,
                "warning": "", "reason": "auto_unavailable"}
    return {
        "enabled": False,
        "native": False,
        "forced": False,
        "warning": "当前端点不支持原生联网搜索，且未配置外部搜索后端（档案 search_url）；"
                   "web_search=always 的要求无法满足，本请求将不带联网搜索执行。",
        "reason": "offline_degraded",
    }


def search_external(url: str, query: str, api_key: str = "",
                    timeout: float = EXTERNAL_TIMEOUT) -> Dict[str, Any]:
    """调用外部 HTTP 搜索后端。

    契约：POST {query: str} → 200 {"results": [{"title": str, "url": str,
    "snippet": str}]}。响应不符合契约时明确失败（不伪造）。
    """
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        resp = requests.post((url or "").strip(), headers=headers,
                             json={"query": query}, timeout=timeout)
    except requests.Timeout:
        return {"ok": False, "error": f"外部搜索后端超时：{url}"}
    except requests.RequestException as exc:
        return {"ok": False, "error": f"无法连接外部搜索后端 {url}：{exc.__class__.__name__}"}
    if resp.status_code != 200:
        return {"ok": False, "error": f"外部搜索后端 HTTP {resp.status_code}"}
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": "外部搜索后端返回非 JSON"}
    results = data.get("results") or data.get("items") or []
    cleaned: List[Dict[str, str]] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        cleaned.append({
            "title": str(r.get("title", "") or ""),
            "url": str(r.get("url", "") or ""),
            "snippet": str(r.get("snippet", "") or r.get("text", "") or ""),
        })
    return {"ok": True, "results": cleaned, "error": ""}


def format_results(results: List[Dict[str, str]]) -> str:
    lines = []
    for i, r in enumerate(results, start=1):
        lines.append(f"{i}. {r.get('title') or r.get('url')}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet']}")
        if r.get("url"):
            lines.append(f"   {r['url']}")
    return "\n".join(lines) or "（无结果）"


def offline_result(profile_id: str, query: str) -> Dict[str, Any]:
    """离线降级的统一警告信息。"""
    return {
        "warning": f"联网搜索不可用（{query!r} 未执行联网）："
                   "当前端点无原生 web_search 且未配置外部搜索后端。",
    }

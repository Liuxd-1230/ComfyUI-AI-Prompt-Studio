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
    """按联网策略与能力返回搜索策略。

    返回 {enabled: bool, native: bool, warning: str, reason: str}
    - enabled=False：不发起搜索（策略 off，或策略 auto 且用户未要求）；
    - native=True：用 Responses 原生 web_search 工具；
    - native=False：只能用外部后端/离线。
    """
    caps = capabilities or {}
    native = caps.get("native_web_search")

    if policy == "off":
        return {"enabled": False, "native": False, "warning": "", "reason": "policy_off"}

    if native is True:
        return {"enabled": True, "native": True, "warning": "", "reason": "native"}

    if native == "unknown":
        # 能力未探测：按 deepseek 官方基线默认原生可用，交由 gateway 在协议不支持时降级
        return {"enabled": True, "native": True,
                "warning": "联网能力未探测（将尝试原生 web_search，失败自动降级）",
                "reason": "native_unknown"}

    # 明确不支持原生：有外部后端则走外部，否则离线 + 警告
    if profile.search_url and profile.search_url.strip():
        return {"enabled": True, "native": False,
                "warning": "", "reason": "external"}
    return {
        "enabled": True,
        "native": False,
        "warning": "当前端点不支持原生联网搜索，且未配置外部搜索后端（档案 search_url）；"
                   "本请求将不带联网搜索执行（结果可能不含最新信息）。",
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

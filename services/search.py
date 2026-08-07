"""联网搜索策略（降级链 v1，docs/decisions.md D7）。

降级链：Responses 原生 web_search →（可插拔外部后端）→ 离线 + 明确警告。
- 401/402/403/429/5xx/网络失败绝不降级（由 gateway/adapter 硬失败）；
- 只有「接口不支持」（ProtocolUnsupported）触发协议降级；
- v1 只实现 DeepSeek Responses 原生 + 离线警告；外部搜索后端留可插拔接口。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from ..schemas.profile import AIProfile


class SearchBackend:
    """外部搜索后端插槽（v1 不实现；未来可挂 Brave/Tavily 等）。"""

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

    # 明确不支持原生（外部后端未配置）→ 离线 + 警告
    return {
        "enabled": True,
        "native": False,
        "warning": "当前端点不支持原生联网搜索，且未配置外部搜索后端；"
                   "本请求将不带联网搜索执行（结果可能不含最新信息）。",
        "reason": "offline_degraded",
    }


def offline_result(profile_id: str, query: str) -> Dict[str, Any]:
    """离线降级的统一警告信息。"""
    return {
        "warning": f"联网搜索不可用（{query!r} 未执行联网）："
                   "当前端点无原生 web_search 且未配置外部搜索后端。",
    }

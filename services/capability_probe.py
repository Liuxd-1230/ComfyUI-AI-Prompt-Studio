"""模型能力探测：验证认证、拉取模型列表、给出能力基线，并缓存（可手动重跑）。

探测结果写入 ConfigStore.capability_cache，key 为 profile_id。
所有探测函数不抛网络异常：错误以 error 字段返回，由调用方决定展示。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import requests

from ..schemas.profile import AIProfile

DEFAULT_TIMEOUT = 15.0

# 已知 DeepSeek 具体模型能力基线（官方文档，2026-08-07 查证，来源见 docs/research.md）。
# 能力必须按「具体模型」判定，而不是 provider==deepseek 一刀切：
# - deepseek-v4-flash：Responses API 与原生 web_search 工具均可用（仅 Responses 路径支持）；
#   文本 API（图片以占位符替换）→ vision/files 均不可用；
#   Chat json_schema 未文档化 → structured_output 走提示词约束+解析修复（False）。
# - deepseek-v4-pro：Responses 支持计划 2026-08 初上线，当前不可用 → responses=False。
DEEPSEEK_MODEL_CAPS = {
    "deepseek-v4-flash": {
        "responses": True,
        "chat_completions": True,
        "function_tools": True,
        "native_web_search": True,
        "structured_output": False,
        "vision": False,
        "files": False,
    },
    "deepseek-v4-pro": {
        "responses": False,
        "chat_completions": True,
        "function_tools": True,
        "native_web_search": False,
        "structured_output": False,
        "vision": False,
        "files": False,
    },
}


def _match_deepseek_model(model: str, models) -> Optional[str]:
    """在档案配置的 model 与 /models 列表里匹配已知模型键（精确或包含关系）。"""
    candidates = [model or ""] + [m for m in (models or []) if isinstance(m, str)]
    for cand in candidates:
        c = cand.strip()
        if not c:
            continue
        for key in DEEPSEEK_MODEL_CAPS:
            if c == key or key in c or c in key:
                return key
    return None


def deepseek_known_responses(model: str) -> Optional[bool]:
    """按模型名给出 Responses 可用性；不在已知表内返回 None（网关按保守处理）。"""
    key = _match_deepseek_model(model or "", [])
    if key is None:
        return None
    return bool(DEEPSEEK_MODEL_CAPS[key]["responses"])


def _status_kind(status: int) -> str:
    if status in (401,):
        return "auth_error"
    if status == 402:
        return "insufficient_balance"
    if status == 403:
        return "forbidden"
    if status == 429:
        return "rate_limit"
    if 400 <= status < 500:
        return "invalid_request"
    if status >= 500:
        return "server_error"
    return "unknown"


def probe_profile(profile: AIProfile, api_key: str, timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """对单个档案执行能力探测。

    返回 dict：
    {
      "responses": bool|"unknown", "chat_completions": bool|"unknown",
      "function_tools": bool|"unknown", "native_web_search": bool|str,
      "structured_output": bool|"unknown", "vision": bool,
      "model_listing": bool, "models": [...],
      "auth_ok": bool, "error": str|None, "http_status": int,
      "probed_at": iso
    }
    """
    caps: Dict[str, Any] = {
        "responses": "unknown",
        "chat_completions": "unknown",
        "function_tools": "unknown",
        "native_web_search": "unknown",
        "structured_output": "unknown",
        "vision": False,
        "files": False,
        "model_listing": False,
        "models": [],
        "auth_ok": False,
        "error": None,
        "http_status": 0,
        "probed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    if not api_key:
        caps["error"] = "未配置 API Key，无法探测"
        return caps

    base = (profile.base_url or "").rstrip("/")
    if not base:
        caps["error"] = "base_url 为空"
        return caps

    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        resp = requests.get(f"{base}/models", headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        caps["error"] = f"无法连接 {base}：{exc.__class__.__name__}"
        return caps

    if resp.status_code == 200:
        try:
            payload = resp.json()
            caps["models"] = [m.get("id", "") for m in payload.get("data", [])]
        except Exception:  # noqa: BLE001 - 非 JSON 响应
            caps["models"] = []
        caps["model_listing"] = True
        caps["auth_ok"] = True
    else:
        caps["http_status"] = resp.status_code
        caps["error"] = f"模型列表请求失败 HTTP {resp.status_code}"
        return caps

    # 已知能力基线（官方文档白名单推断；按「具体模型」判定，而非 provider 一刀切）
    host = (base or "").lower()
    if profile.provider == "deepseek" or "deepseek.com" in host or "api.deepseek" in host:
        key = _match_deepseek_model(profile.model, caps["models"])
        if key is not None:
            caps.update(DEEPSEEK_MODEL_CAPS[key])
            caps["capability_basis"] = f"per_model:{key}"
        else:
            # 未知 DeepSeek 模型：保守基线（chat 可用；responses/web_search 未知，
            # 由网关按 deepseek_known_responses 静态表兜底，不再默认 Responses）
            caps.update(
                responses="unknown",
                chat_completions=True,
                function_tools=True,
                native_web_search=False,
                structured_output=False,
                vision=False,
                files=False,
            )
            caps["capability_basis"] = "deepseek_unknown_model_conservative"
    else:
        # 通用 OpenAI 兼容端点：chat 与 function tools 大概率可用，responses 未知
        caps.update(
            responses="unknown",
            chat_completions=True,
            function_tools=True,
            native_web_search=False,
            structured_output=True,
            vision=False,
            files=False,
        )
        caps["capability_basis"] = "openai_compatible_generic"

    if profile.vision_model or profile.vision_base_url:
        caps["vision"] = True  # 用户显式配置了视觉端点，视为可用

    return caps


def merge_capabilities(existing: Dict[str, Any], fresh: Dict[str, Any]) -> Dict[str, Any]:
    """用新探测结果合并旧缓存：未知("unknown")字段保留旧值。"""
    merged = dict(existing or {})
    for k, v in (fresh or {}).items():
        if v == "unknown" and merged.get(k) not in (None, "unknown"):
            continue
        merged[k] = v
    return merged

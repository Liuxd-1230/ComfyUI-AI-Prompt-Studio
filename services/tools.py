"""函数工具注册表 + 执行（P1：function tool execution loop）。

产品决策：
- MAX_TOOL_ROUNDS = 4，不暴露到节点 UI（产品决策 §21/P1）；
- 工具定义只在请求启用 tools 时随协议发送（OpenAI 兼容结构）；
- 工具执行失败 → 错误作为输出回给模型继续（不抛异常、不伪造成功）；
- search 工具走档案 search_url 外部后端（与网关外部搜索注入同源）。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from ..schemas.profile import AIProfile
from . import search

MAX_TOOL_ROUNDS = 4


def tool_definitions() -> List[Dict[str, Any]]:
    """OpenAI 兼容 function tool 定义列表（不含外层 type 包装）。"""
    return [
        {
            "name": "now",
            "description": "获取当前本地时间（ISO 8601 格式）。无需参数。",
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "name": "search",
            "description": "外部联网搜索（需要档案配置 search_url 外部搜索后端）。"
                           "返回带标题、摘要与链接的结果列表。",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string",
                                         "description": "要搜索的关键词/问题"}},
                "required": ["query"],
            },
        },
    ]


def execute_tool(name: str, arguments_json: str, profile: AIProfile) -> Dict[str, Any]:
    """执行一次工具调用。

    返回 {"ok": bool, "output": str, "error": str}；任何失败都返回错误文本，
    绝不抛异常、绝不伪造结果。
    """
    try:
        args = json.loads(arguments_json or "{}")
        if not isinstance(args, dict):
            args = {}
    except ValueError:
        args = {}
    if name == "now":
        return _tool_now(args)
    if name == "search":
        return _tool_search(args, profile)
    return {"ok": False, "error": f"未知工具 {name!r}", "output": ""}


def _tool_now(args: Dict[str, Any]) -> Dict[str, Any]:
    import time

    try:
        from datetime import datetime, timezone
    except Exception:  # noqa: BLE001
        from datetime import datetime

        return {"ok": True, "output": datetime.now().isoformat(timespec="seconds")}
    return {
        "ok": True,
        "output": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "note": "本地时区时间",  # 供模型理解语义，非伪造数据
    }


def _tool_search(args: Dict[str, Any], profile: AIProfile) -> Dict[str, Any]:
    query = str(args.get("query", "")).strip()
    if not query:
        return {"ok": False, "error": "search 需要 query 参数", "output": ""}
    url = (profile.search_url or "").strip()
    if not url:
        return {"ok": False,
                "error": "未配置外部搜索后端（档案 search_url 为空），无法执行 search",
                "output": ""}
    res = search.search_external(url, query)
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error", "外部搜索失败"), "output": ""}
    results = res.get("results", [])
    return {"ok": True, "output": search.format_results(results),
            "count": len(results)}

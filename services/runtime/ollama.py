"""Ollama 后端（docs/research.md：Ollama 无 /api/load|unload 端点）。

- 状态：GET /api/ps（正在运行模型）
- 列表：GET /api/tags
- 加载：POST /api/generate 空 prompt 预热（keep_alive 5m）
- 卸载：POST /api/generate keep_alive=0
"""
from __future__ import annotations

from typing import Any, Dict, List

from .base import RuntimeBackend


class OllamaBackend(RuntimeBackend):
    kind = "ollama"
    default_url = "http://127.0.0.1:11434"

    def status(self) -> Dict[str, Any]:
        res = self._request("GET", "/api/ps")
        if not res.get("ok"):
            return {"available": False, "models": [], "error": res.get("error", "")}
        payload = res.get("json", {})
        models = []
        for m in payload.get("models", []) or []:
            if isinstance(m, dict) and m.get("name"):
                models.append(m["name"])
        return {"available": True, "models": models, "error": ""}

    def list_models(self) -> List[str]:
        res = self._request("GET", "/api/tags")
        if not res.get("ok"):
            return []
        names = []
        for m in res.get("json", {}).get("models", []) or []:
            if isinstance(m, dict) and m.get("name"):
                names.append(m["name"])
        return names

    def load(self, model: str) -> Dict[str, Any]:
        if not model:
            return {"ok": False, "error": "model 不能为空"}
        body = {"model": model, "prompt": "", "stream": False, "keep_alive": "5m"}
        res = self._request("POST", "/api/generate", json=body)
        if not res.get("ok"):
            return self._check_missing(res, model)
        return {"ok": True, "model": model, "detail": "已预热加载"}

    def unload(self, model: str) -> Dict[str, Any]:
        if not model:
            return {"ok": False, "error": "model 不能为空"}
        body = {"model": model, "prompt": "", "stream": False, "keep_alive": 0}
        res = self._request("POST", "/api/generate", json=body)
        if not res.get("ok"):
            return self._check_missing(res, model)
        return {"ok": True, "model": model, "detail": "已卸载"}

    @staticmethod
    def _check_missing(res: Dict[str, Any], model: str) -> Dict[str, Any]:
        error = res.get("error", "")
        if "not found" in error.lower() or "不存在" in error:
            return {"ok": False, "model": model,
                    "error": f"模型不存在或尚未拉取：{model}"}
        return res

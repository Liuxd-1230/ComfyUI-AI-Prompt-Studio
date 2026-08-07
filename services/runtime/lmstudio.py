"""LM Studio 后端（docs/research.md：v1 支持 /api/v1/models/load|unload，v0 只读）。

- 版本探测：GET /api/v0/models 可达 → v0（只读）；否则按 v1 处理
- v1 状态/列表：GET /api/v1/models；加载：POST /api/v1/models/load；卸载：POST /api/v1/models/unload
- v0：状态/列表只读；load/unload 给出可读错误
"""
from __future__ import annotations

from typing import Any, Dict, List

from .base import RuntimeBackend


class LMStudioBackend(RuntimeBackend):
    kind = "lmstudio"
    default_url = "http://127.0.0.1:1234"

    def __init__(self, base_url: str = ""):
        super().__init__(base_url)
        self._version: str | None = None  # "v0" | "v1"，探测一次后缓存

    def _detect_version(self) -> str:
        if self._version:
            return self._version
        res = self._request("GET", "/api/v0/models")
        self._version = "v0" if res.get("ok") else "v1"
        return self._version

    def _model_ids(self, path: str) -> List[str]:
        res = self._request("GET", path)
        ids = []
        for m in res.get("json", {}).get("data", []) or []:
            if isinstance(m, dict) and m.get("id"):
                ids.append(m["id"])
        return ids

    def status(self) -> Dict[str, Any]:
        version = self._detect_version()
        path = "/api/v0/models" if version == "v0" else "/api/v1/models"
        res = self._request("GET", path)
        if not res.get("ok"):
            return {"available": False, "models": [], "error": res.get("error", "")}
        return {"available": True, "models": self._model_ids(path),
                "version": version, "error": ""}

    def list_models(self) -> List[str]:
        version = self._detect_version()
        path = "/api/v0/models" if version == "v0" else "/api/v1/models"
        return self._model_ids(path)

    def load(self, model: str) -> Dict[str, Any]:
        if not model:
            return {"ok": False, "error": "model 不能为空"}
        if self._detect_version() == "v0":
            return {"ok": False, "error": "当前 LM Studio 为 v0（只读），不支持热加载/卸载；请升级到 v1 或手动在 LM Studio 中加载。"}
        res = self._request("POST", "/api/v1/models/load", json={"model": model})
        if not res.get("ok"):
            return self._check_missing(res, model)
        return {"ok": True, "model": model, "detail": "已加载"}

    def unload(self, model: str) -> Dict[str, Any]:
        if not model:
            return {"ok": False, "error": "model 不能为空"}
        if self._detect_version() == "v0":
            return {"ok": False, "error": "当前 LM Studio 为 v0（只读），不支持热加载/卸载；请升级到 v1 或手动在 LM Studio 中卸载。"}
        res = self._request("POST", "/api/v1/models/unload", json={"model": model})
        if not res.get("ok"):
            return self._check_missing(res, model)
        return {"ok": True, "model": model, "detail": "已卸载"}

    @staticmethod
    def _check_missing(res: Dict[str, Any], model: str) -> Dict[str, Any]:
        error = res.get("error", "")
        low = error.lower()
        if "not found" in low or "does not exist" in low or "404" in low:
            return {"ok": False, "model": model,
                    "error": f"模型未加载或不存在：{model}"}
        return res

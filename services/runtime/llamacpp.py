"""llama.cpp server 后端（POST /models/load|unload + GET /v1/models）。"""
from __future__ import annotations

from typing import Any, Dict, List

from .base import RuntimeBackend


class LlamaCppBackend(RuntimeBackend):
    kind = "llamacpp"
    default_url = "http://127.0.0.1:8080"

    def _loaded_ids(self) -> List[str]:
        res = self._request("GET", "/v1/models")
        ids = []
        for m in res.get("json", {}).get("data", []) or []:
            if isinstance(m, dict) and m.get("id"):
                ids.append(m["id"])
        return ids

    def status(self) -> Dict[str, Any]:
        res = self._request("GET", "/v1/models")
        if not res.get("ok"):
            return {"available": False, "models": [], "error": res.get("error", "")}
        return {"available": True, "models": self._loaded_ids(), "error": ""}

    def list_models(self) -> List[str]:
        return self._loaded_ids()

    def load(self, model: str) -> Dict[str, Any]:
        if not model:
            return {"ok": False, "error": "model 不能为空"}
        # llama.cpp 官方 body 字段是 {"model": ...}（不是 {"id": ...}），已按源码查证
        res = self._request("POST", "/models/load", json={"model": model})
        if not res.get("ok"):
            return self._check_missing(res, model)
        return {"ok": True, "model": model, "detail": "已加载"}

    def unload(self, model: str) -> Dict[str, Any]:
        if not model:
            return {"ok": False, "error": "model 不能为空"}
        res = self._request("POST", "/models/unload", json={"model": model})
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

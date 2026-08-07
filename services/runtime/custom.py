"""自定义 OpenAI 兼容服务后端（kind=custom）。

约定（README 说明）：状态/模型列表走 GET /v1/models（OpenAI 兼容通用）；
load/unload 走 llama.cpp 风格 POST /models/load|unload {"model": ...}——
这是自定义 OpenAI 兼容服务最通用的约定。端点不支持该操作时返回明确错误，
不伪装成功（产品决策：custom 是真实适配器，不是摆设选项）。
"""
from __future__ import annotations

from typing import Any, Dict, List

from .base import RuntimeBackend


class CustomHTTPBackend(RuntimeBackend):
    kind = "custom"
    default_url = "http://127.0.0.1:8080"

    def _loaded_ids(self, res: Dict[str, Any] = None) -> List[str]:
        if res is None:
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
        return {"available": True, "models": self._loaded_ids(res), "error": ""}

    def list_models(self) -> List[str]:
        return self._loaded_ids()

    def load(self, model: str) -> Dict[str, Any]:
        if not model:
            return {"ok": False, "error": "model 不能为空"}
        res = self._request("POST", "/models/load", json={"model": model})
        return self._op_result("load", model, res)

    def unload(self, model: str) -> Dict[str, Any]:
        if not model:
            return {"ok": False, "error": "model 不能为空"}
        res = self._request("POST", "/models/unload", json={"model": model})
        return self._op_result("unload", model, res)

    @staticmethod
    def _op_result(op: str, model: str, res: Dict[str, Any]) -> Dict[str, Any]:
        if res.get("ok"):
            return {"ok": True, "model": model, "detail": "已" + ("加载" if op == "load" else "卸载")}
        error = res.get("error", "")
        low = error.lower()
        if "404" in error or "405" in error or "not found" in low or "no such" in low:
            return {"ok": False, "model": model,
                    "error": f"该自定义端点不支持 {op} 操作（{error}）"}
        return res

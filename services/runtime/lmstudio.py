"""LM Studio 后端（docs/research.md：v1 官方推荐；v0 只读降级）。

官方 REST（2026-08-07 查证，docs/research.md §8）：
- 版本探测：v1 优先（GET /api/v1/models）→ 失败再试 v0（GET /api/v0/models）→ 都失败 unavailable；
- v1 列表：GET /api/v1/models → {"models": [{..., "loaded_instances": [{"id": ..., "config": ...}]}]}
  （注意 v1 顶层是 models 键，v0 是 data 键）；
- load：POST /api/v1/models/load，请求体 {"model": ...}；响应含 instance_id；
- unload：POST /api/v1/models/unload，请求体 {"instance_id": ...}（官方唯一字段，不能用 model）。
- v0：状态/列表只读；load/unload 给出可读错误。
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
        # load 成功时保存的 instance_id（model → instance_id）；unload 优先使用
        self._instance_ids: Dict[str, str] = {}

    def _detect_version(self) -> str:
        if self._version:
            return self._version
        # v1 优先（官方推荐）；v0 为只读降级
        res = self._request("GET", "/api/v1/models")
        if res.get("ok"):
            self._version = "v1"
            return self._version
        res = self._request("GET", "/api/v0/models")
        if res.get("ok"):
            self._version = "v0"
            return self._version
        self._version = "unavailable"
        return self._version

    def _model_ids(self, path: str) -> List[str]:
        res = self._request("GET", path)
        payload = res.get("json", {}) or {}
        entries = payload.get("models") or payload.get("data") or []
        ids = []
        for m in entries:
            if isinstance(m, dict) and m.get("id"):
                ids.append(m["id"])
        return ids

    def _loaded_instance_id_for(self, model: str) -> str:
        """在 v1 已加载实例里找 model 对应的 instance_id（官方：loaded_instances[].id）。"""
        res = self._request("GET", "/api/v1/models")
        if not res.get("ok"):
            return ""
        for m in res.get("json", {}).get("models", []) or []:
            if not isinstance(m, dict) or m.get("id") != model:
                continue
            for inst in m.get("loaded_instances") or []:
                if isinstance(inst, dict) and inst.get("id"):
                    return str(inst["id"])
        return ""

    def status(self) -> Dict[str, Any]:
        version = self._detect_version()
        if version == "unavailable":
            return {"available": False, "models": [], "version": "unavailable",
                    "error": "无法探测 LM Studio（v1 与 v0 models 接口均不可达）"}
        path = "/api/v0/models" if version == "v0" else "/api/v1/models"
        res = self._request("GET", path)
        if not res.get("ok"):
            return {"available": False, "models": [], "error": res.get("error", "")}
        return {"available": True, "models": self._model_ids(path),
                "version": version, "error": ""}

    def list_models(self) -> List[str]:
        version = self._detect_version()
        if version == "unavailable":
            return []
        path = "/api/v0/models" if version == "v0" else "/api/v1/models"
        return self._model_ids(path)

    def load(self, model: str) -> Dict[str, Any]:
        if not model:
            return {"ok": False, "error": "model 不能为空"}
        if self._detect_version() != "v1":
            return {"ok": False, "error": "当前 LM Studio 为 v0（只读），不支持热加载/卸载；请升级到 v1 或手动在 LM Studio 中加载。"}
        res = self._request("POST", "/api/v1/models/load", json={"model": model})
        if not res.get("ok"):
            return self._check_missing(res, model)
        # 官方 load 响应含 instance_id；保存供 unload 使用
        iid = str(res.get("json", {}).get("instance_id", "") or "")
        if iid:
            self._instance_ids[model] = iid
        return {"ok": True, "model": model, "instance_id": iid, "detail": "已加载"}

    def unload(self, model: str) -> Dict[str, Any]:
        if not model:
            return {"ok": False, "error": "model 不能为空"}
        if self._detect_version() != "v1":
            return {"ok": False, "error": "当前 LM Studio 为 v0（只读），不支持热加载/卸载；请升级到 v1 或手动在 LM Studio 中卸载。"}
        instance_id = self._instance_ids.get(model) or self._loaded_instance_id_for(model)
        if not instance_id:
            return {"ok": False, "model": model,
                    "error": f"未找到模型 {model} 的已加载实例（instance_id）；请先 load 或检查模型名"}
        res = self._request("POST", "/api/v1/models/unload",
                            json={"instance_id": instance_id})
        if not res.get("ok"):
            self._instance_ids.pop(model, None)
            return self._check_missing(res, model)
        self._instance_ids.pop(model, None)
        return {"ok": True, "model": model, "instance_id": instance_id,
                "detail": "已卸载"}

    @staticmethod
    def _check_missing(res: Dict[str, Any], model: str) -> Dict[str, Any]:
        error = res.get("error", "")
        low = error.lower()
        if "not found" in low or "does not exist" in low or "404" in low:
            return {"ok": False, "model": model,
                    "error": f"模型未加载或不存在：{model}"}
        return res

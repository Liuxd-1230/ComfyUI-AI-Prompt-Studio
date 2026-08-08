"""LM Studio 后端（docs/research.md：v1 官方推荐；v0 只读降级）。

官方 REST（2026-08-07 查证，docs/research.md §8；0.2.1a 复核 lmstudio.ai/docs/developer/rest/list）：
- 版本探测：v1 优先（GET /api/v1/models）→ 失败再试 v0（GET /api/v0/models）→ 都失败 unavailable；
- v1 列表：GET /api/v1/models → {"models": [{..., "key": ..., "loaded_instances": [{"id": ..., "config": ...}]}]}
  （注意 v1 模型标识字段是 **key**（非 id），顶层是 models 键；v0 是 data 键 + id 字段；
  实现同时接受 key/id，兼容两代官方结构）；
- load：POST /api/v1/models/load，请求体 {"model": ...}；响应含 instance_id；
- unload：POST /api/v1/models/unload，请求体 {"instance_id": ...}（官方唯一字段，不能用 model）。
- v0：状态/列表只读；load/unload 给出可读错误。
"""
from __future__ import annotations

import os
from typing import Any, Dict, List

from .base import RuntimeBackend


class LMStudioBackend(RuntimeBackend):
    kind = "lmstudio"
    default_url = "http://127.0.0.1:1234"

    def __init__(self, base_url: str = ""):
        super().__init__(base_url)
        self._version: str | None = None  # "v0" | "v1"，探测一次后缓存
        self._probe_error = ""
        # load 成功时保存的 instance_id（model → instance_id）；unload 优先使用
        self._instance_ids: Dict[str, str] = {}

    def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        token = os.environ.get("LM_STUDIO_API_TOKEN", "").strip()
        if token:
            headers = dict(kwargs.pop("headers", {}) or {})
            headers["Authorization"] = f"Bearer {token}"
            kwargs["headers"] = headers
        return super()._request(method, path, **kwargs)

    def _detect_version(self) -> str:
        if self._version:
            return self._version
        # v1 优先（官方推荐）；v0 为只读降级
        res = self._request("GET", "/api/v1/models")
        if res.get("ok"):
            self._version = "v1"
            return self._version
        first_error = res.get("error", "")
        res = self._request("GET", "/api/v0/models")
        if res.get("ok"):
            self._version = "v0"
            return self._version
        self._version = "unavailable"
        self._probe_error = "；".join(x for x in (first_error, res.get("error", "")) if x)
        return self._version

    def _model_ids(self, path: str) -> List[str]:
        res = self._request("GET", path)
        payload = res.get("json", {}) or {}
        entries = payload.get("models") or payload.get("data") or []
        ids = []
        for m in entries:
            if not isinstance(m, dict):
                continue
            # v1 官方模型标识字段是 key（v0 是 id）；同时兼容两代官方结构
            model_key = m.get("key") or m.get("id")
            if model_key:
                ids.append(str(model_key))
        return ids

    def _loaded_model_keys(self) -> List[str]:
        """v1 模型目录中只返回确有 loaded_instances 的模型 key。"""
        res = self._request("GET", "/api/v1/models")
        if not res.get("ok"):
            return []
        loaded: List[str] = []
        for model in res.get("json", {}).get("models", []) or []:
            if not isinstance(model, dict) or not (model.get("loaded_instances") or []):
                continue
            key = model.get("key") or model.get("id")
            if key:
                loaded.append(str(key))
        return loaded

    def _v1_model_snapshot(self, model: str) -> Dict[str, Any]:
        """读取指定模型的权威目录状态，区分不存在与已经卸载。"""
        res = self._request("GET", "/api/v1/models")
        if not res.get("ok"):
            return {"ok": False, "found": False, "instance_ids": [],
                    "error": res.get("error", "无法读取 LM Studio 模型目录")}
        for entry in res.get("json", {}).get("models", []) or []:
            if not isinstance(entry, dict):
                continue
            model_key = entry.get("key") or entry.get("id")
            if model_key != model:
                continue
            instance_ids = [
                str(instance["id"])
                for instance in entry.get("loaded_instances") or []
                if isinstance(instance, dict) and instance.get("id")
            ]
            return {"ok": True, "found": True, "instance_ids": instance_ids,
                    "error": ""}
        return {"ok": True, "found": False, "instance_ids": [], "error": ""}

    def status(self) -> Dict[str, Any]:
        version = self._detect_version()
        if version == "unavailable":
            return {"available": False, "models": [], "version": "unavailable",
                    "error": self._probe_error or
                    "无法探测 LM Studio（v1 与 v0 models 接口均不可达）"}
        path = "/api/v0/models" if version == "v0" else "/api/v1/models"
        res = self._request("GET", path)
        if not res.get("ok"):
            return {"available": False, "models": [], "error": res.get("error", "")}
        models = self._model_ids(path) if version == "v0" else self._loaded_model_keys()
        return {"available": True, "models": models,
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
        version = self._detect_version()
        if version == "unavailable":
            return {"ok": False, "error": "无法连接或认证 LM Studio（v1 与 v0 models 接口均不可用）"}
        if version != "v1":
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
        version = self._detect_version()
        if version == "unavailable":
            return {"ok": False, "model": model,
                    "error": "无法连接或认证 LM Studio（v1 与 v0 models 接口均不可用）"}
        if version != "v1":
            return {"ok": False, "error": "当前 LM Studio 为 v0（只读），不支持热加载/卸载；请升级到 v1 或手动在 LM Studio 中卸载。"}
        snapshot = self._v1_model_snapshot(model)
        if not snapshot.get("ok"):
            return {"ok": False, "model": model,
                    "error": snapshot.get("error", "无法读取 LM Studio 模型目录")}
        instance_ids = list(snapshot.get("instance_ids", []))
        cached = self._instance_ids.get(model)
        # 目录中已找到模型时，以 loaded_instances 为权威，避免拿过期缓存
        # 重复 POST；仅在目录尚未同步到刚 load 的模型时使用本进程缓存。
        if not snapshot.get("found") and cached and cached not in instance_ids:
            instance_ids.insert(0, cached)
        if not instance_ids:
            self._instance_ids.pop(model, None)
            if snapshot.get("found"):
                return {"ok": True, "model": model, "already_unloaded": True,
                        "instance_id": "", "instance_ids": [],
                        "detail": "模型已处于卸载状态"}
            return {"ok": False, "model": model,
                    "error": f"LM Studio 模型目录中不存在 {model}；请检查模型 key"}
        unloaded: List[str] = []
        errors: List[str] = []
        for instance_id in instance_ids:
            res = self._request("POST", "/api/v1/models/unload",
                                json={"instance_id": instance_id})
            if res.get("ok"):
                unloaded.append(instance_id)
            else:
                errors.append(self._check_missing(res, model).get("error", "卸载失败"))
        self._instance_ids.pop(model, None)
        if errors:
            return {"ok": False, "model": model, "instance_ids": unloaded,
                    "error": "；".join(errors), "detail": f"已卸载 {len(unloaded)} 个实例"}
        return {"ok": True, "model": model,
                "instance_id": unloaded[0], "instance_ids": unloaded,
                "detail": f"已卸载 {len(unloaded)} 个实例"}

    @staticmethod
    def _check_missing(res: Dict[str, Any], model: str) -> Dict[str, Any]:
        error = res.get("error", "")
        low = error.lower()
        if "not found" in low or "does not exist" in low or "404" in low:
            return {"ok": False, "model": model,
                    "error": f"模型未加载或不存在：{model}"}
        return res

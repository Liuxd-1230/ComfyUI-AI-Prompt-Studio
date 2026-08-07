"""运行时后端基类：统一状态/列模型/加载/卸载接口与 HTTP 错误包装。

原则：只操作独立运行的本地服务；错误始终以可读文本返回（不抛给节点层裸异常）；
模型不存在/接口不支持给出明确区分，便于用户修复。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

import requests

logger = logging.getLogger("ai_prompt_studio.runtime")


class RuntimeFailure(Exception):
    """运行时操作失败（可读中文信息）。"""


class RuntimeBackend:
    kind = "base"
    default_url = ""

    def __init__(self, base_url: str = ""):
        self.base_url = (base_url or self.default_url).rstrip("/")
        self.timeout = 10.0

    # ------------------------------------------------------------ 公共 HTTP
    def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        kwargs.setdefault("timeout", self.timeout)
        try:
            resp = requests.request(method, url, **kwargs)
        except requests.Timeout:
            return self._err(f"连接超时：{url}")
        except requests.RequestException as exc:
            return self._err(f"无法连接 {url}：{exc.__class__.__name__}")
        if resp.status_code == 200:
            try:
                return {"ok": True, "status_code": 200, "json": resp.json()}
            except Exception:  # noqa: BLE001 - 非 JSON 也算成功（如空 body）
                return {"ok": True, "status_code": 200, "json": {}}
        detail = self._detail(resp)
        return self._err(f"HTTP {resp.status_code}：{detail}")

    @staticmethod
    def _detail(resp) -> str:
        try:
            text = resp.text[:300]
            return text if text.strip() else resp.reason or ""
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _err(message: str) -> Dict[str, Any]:
        return {"ok": False, "error": message}

    # ------------------------------------------------------------ 标准接口
    def status(self) -> Dict[str, Any]:
        """{available: bool, models: [str], error: str}"""
        raise NotImplementedError

    def list_models(self) -> List[str]:
        raise NotImplementedError

    def load(self, model: str) -> Dict[str, Any]:
        raise NotImplementedError

    def unload(self, model: str) -> Dict[str, Any]:
        raise NotImplementedError

    def unload_all(self) -> Dict[str, Any]:
        errors = []
        unloaded = []
        # 卸载当前已加载（status 的 models），而不是全部可拉取模型
        for m in self.status().get("models", []):
            res = self.unload(m)
            if res.get("ok"):
                unloaded.append(m)
            else:
                errors.append(res.get("error", "未知错误"))
        if errors:
            return {"ok": False, "unloaded": unloaded, "error": "；".join(errors)}
        return {"ok": True, "unloaded": unloaded, "error": ""}

    def summary(self) -> Dict[str, Any]:
        """节点展示用统一结构。"""
        st = self.status()
        return {
            "backend": self.kind,
            "url": self.base_url,
            "available": st.get("available", False),
            "models": st.get("models", []),
            "error": st.get("error", ""),
        }

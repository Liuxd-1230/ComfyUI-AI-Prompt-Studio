"""本地运行时动作服务层（节点与 Settings /runtime 路由共用的同一实现）。

产品决策（P0）：Settings /runtime 必须调用与本仓库 Runtime Control 节点相同的
服务层，而不是各自实现。run_runtime_action 返回统一 dict：
{ok, backend, action, model, status, models, result, error, ...}
"""
from __future__ import annotations

from typing import Any, Dict

from . import create_backend

RUNTIME_ACTIONS = ["status", "list_models", "load", "unload", "reload", "unload_all"]


def run_runtime_action(backend: str, action: str, url: str = "",
                       model: str = "") -> Dict[str, Any]:
    """执行一次运行时动作；任何失败都以 error 字段返回，不抛异常。"""
    base: Dict[str, Any] = {"backend": backend, "action": action,
                            "model": model.strip(), "ok": False, "error": ""}
    try:
        runtime = create_backend(backend, url)
    except ValueError as exc:
        base["error"] = str(exc)
        return base

    try:
        if action == "status":
            st = runtime.status()
            base.update(ok=bool(st.get("available")), status=st,
                        models=st.get("models", []),
                        error=st.get("error", ""))
            return base

        if action == "list_models":
            st = runtime.status()
            if not st.get("available"):
                base.update(ok=False, models=[],
                            error=st.get("error") or "运行时不可用")
                return base
            base.update(ok=True, models=runtime.list_models())
            return base

        if action in ("load", "unload"):
            if not model.strip():
                base["error"] = "load/unload 需要填写 model"
                return base
            res = runtime.load(model.strip()) if action == "load" \
                else runtime.unload(model.strip())
            base.update(ok=bool(res.get("ok")), result=res,
                        error=res.get("error", ""))
            return base

        if action == "reload":
            if not model.strip():
                base["error"] = "reload 需要填写 model"
                return base
            un = runtime.unload(model.strip())
            if not un.get("ok"):
                base.update(ok=False, result=un, error=un.get("error", ""))
                return base
            ld = runtime.load(model.strip())
            base.update(ok=bool(ld.get("ok")), result={
                "ok": ld.get("ok"), "unload": un.get("detail", ""),
                "load": ld.get("detail", ""), "error": ld.get("error", "")},
                error=ld.get("error", ""))
            return base

        if action == "unload_all":
            res = runtime.unload_all()
            base.update(ok=bool(res.get("ok")), result=res,
                        unloaded=res.get("unloaded", []),
                        error=res.get("error", ""))
            return base

        base["error"] = f"未知操作 {action!r}"
        return base
    except Exception as exc:  # noqa: BLE001 - 服务层统一兜底
        base["error"] = str(exc)
        return base

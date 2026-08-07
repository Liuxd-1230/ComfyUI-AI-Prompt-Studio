"""节点 9：Local Runtime Control —— 控制独立运行的本地 LLM 服务。

后端：Ollama / llama.cpp server / LM Studio（services/runtime/）。
只操作独立服务，不把模型加载进 ComfyUI 进程；用于释放显存给图像/视频模型。
"""
from __future__ import annotations

import json

from ..schemas import types
from ..schemas.profile import AIProfile
from ..services.runtime import create_backend

BACKENDS = ["ollama", "llamacpp", "lmstudio", "custom"]
ACTIONS = ["status", "list_models", "load", "unload", "reload", "unload_all"]


class APS_RuntimeControl:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "backend": (BACKENDS, {"default": "ollama",
                                   "tooltip": "本地运行时后端：Ollama / llama.cpp server / LM Studio / 自定义兼容服务"}),
            "action": (ACTIONS, {"default": "status",
                                 "tooltip": "status=查询；list_models=列出已加载；load=加载；unload=卸载；reload=重载；unload_all=全部卸载"}),
            "url": ("STRING", {"default": "", "multiline": False,
                               "tooltip": "服务地址；留空用默认（ollama=http://127.0.0.1:11434, llama.cpp=http://127.0.0.1:8080, lmstudio=http://127.0.0.1:1234）"}),
            "model": ("STRING", {"default": "", "multiline": False,
                                 "tooltip": "模型名（load/unload/reload 需要）"}),
        }, "optional": {
            "AI_PROFILE": (types.AI_PROFILE,),
        }}

    RETURN_TYPES = (types.AI_PROFILE, "STRING", "STRING", "STRING")
    RETURN_NAMES = ("AI_PROFILE", "runtime_status", "loaded_models", "operation_result")
    FUNCTION = "control"
    CATEGORY = "AI Prompt Studio"
    DESCRIPTION = "查询/加载/卸载本地 LLM 模型（独立服务，不加载进 ComfyUI 进程），用于释放显存给图像/视频模型。"

    def control(self, backend, action, url, model, AI_PROFILE=None):
        profile = AIProfile.from_json(AI_PROFILE) if AI_PROFILE else AIProfile()

        try:
            runtime = create_backend(backend, url)
        except ValueError as exc:
            err = str(exc)
            return (profile.node_payload(),
                    json.dumps({"backend": backend, "available": False,
                                "error": err}, ensure_ascii=False),
                    "[]",
                    json.dumps({"ok": False, "error": err}, ensure_ascii=False))

        if action == "status":
            st = runtime.status()
            return (profile.node_payload(),
                    json.dumps(st, ensure_ascii=False),
                    json.dumps(st.get("models", []), ensure_ascii=False),
                    json.dumps({"ok": bool(st.get("available")),
                                "error": st.get("error", "")}, ensure_ascii=False))

        if action == "list_models":
            try:
                models = runtime.list_models()
            except Exception as exc:  # noqa: BLE001
                return (profile.node_payload(), json.dumps({"error": str(exc)}, ensure_ascii=False),
                        "[]", json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            return (profile.node_payload(),
                    json.dumps({"models": models}, ensure_ascii=False),
                    json.dumps(models, ensure_ascii=False),
                    json.dumps({"ok": True, "count": len(models)}, ensure_ascii=False))

        if action in ("load", "unload"):
            if not model.strip():
                raise ValueError("load/unload 需要填写 model")
            res = runtime.load(model.strip()) if action == "load" else runtime.unload(model.strip())
            return (profile.node_payload(),
                    json.dumps({"backend": backend, "model": model.strip()}, ensure_ascii=False),
                    "[]",
                    json.dumps(res, ensure_ascii=False))

        if action == "reload":
            if not model.strip():
                raise ValueError("reload 需要填写 model")
            un = runtime.unload(model.strip())
            if not un.get("ok"):
                return (profile.node_payload(),
                        json.dumps({"backend": backend, "model": model.strip()}, ensure_ascii=False),
                        "[]", json.dumps(un, ensure_ascii=False))
            ld = runtime.load(model.strip())
            return (profile.node_payload(),
                    json.dumps({"backend": backend, "model": model.strip()}, ensure_ascii=False),
                    "[]", json.dumps({"ok": ld.get("ok"),
                                      "unload": un.get("detail", ""),
                                      "load": ld.get("detail", ""),
                                      "error": ld.get("error", "")}, ensure_ascii=False))

        if action == "unload_all":
            res = runtime.unload_all()
            return (profile.node_payload(),
                    json.dumps({"backend": backend, "unloaded": res.get("unloaded", [])},
                               ensure_ascii=False),
                    json.dumps(res.get("unloaded", []), ensure_ascii=False),
                    json.dumps(res, ensure_ascii=False))

        raise ValueError(f"未知操作 {action!r}")

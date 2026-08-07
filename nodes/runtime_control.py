"""节点 9：Local Runtime Control —— 控制独立运行的本地 LLM 服务。

后端：Ollama / llama.cpp server / LM Studio / 自定义兼容服务（services/runtime/）。
动作逻辑与 Settings /runtime 路由共用 services/runtime/control.run_runtime_action
（同一服务层，避免两处实现漂移）。
只操作独立服务，不把模型加载进 ComfyUI 进程；用于释放显存给图像/视频模型。
"""
from __future__ import annotations

import json

from ..schemas import types
from ..schemas.profile import AIProfile
from ..services.runtime.control import RUNTIME_ACTIONS, run_runtime_action

BACKENDS = ["ollama", "llamacpp", "lmstudio", "custom"]


class APS_RuntimeControl:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "backend": (BACKENDS, {"default": "ollama",
                                   "tooltip": "本地运行时后端：Ollama / llama.cpp server / LM Studio / 自定义兼容服务"}),
            "action": (RUNTIME_ACTIONS, {"default": "status",
                                         "tooltip": "status=查询；list_models=列出已加载；load=加载；unload=卸载；reload=重载；unload_all=全部卸载"}),
            "url": ("STRING", {"default": "", "multiline": False,
                               "tooltip": "服务地址；留空用默认（ollama=http://127.0.0.1:11434, llama.cpp=http://127.0.0.1:8080, lmstudio=http://127.0.0.1:1234, custom=http://127.0.0.1:8080）"}),
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
        res = run_runtime_action(backend, action, url, model)

        status_text = json.dumps({
            "backend": backend,
            "action": action,
            "available": res.get("ok"),
            "models": res.get("models", []),
            "error": res.get("error", ""),
        }, ensure_ascii=False)

        loaded = json.dumps(res.get("models", res.get("unloaded", [])),
                            ensure_ascii=False)
        op = json.dumps(res.get("result") or {
            "ok": res.get("ok"), "error": res.get("error", "")}, ensure_ascii=False)
        return (profile.node_payload(), status_text, loaded, op)

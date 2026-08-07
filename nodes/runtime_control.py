"""节点 9：Local Runtime Control —— 控制独立运行的本地 LLM 服务。

Phase 1：注册与数据结构就绪；Phase 2 实现 Ollama / llama.cpp / LM Studio 后端。
"""

import json

from ..schemas import types
from ..schemas.profile import AIProfile

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
        # Phase 2 实现真实后端调用。
        status = {"backend": backend, "action": action, "url": url or "default",
                  "available": False, "error": "本地运行时控制将在 Phase 2 实现"}
        return (profile.node_payload(), json.dumps(status, ensure_ascii=False),
                "[]", json.dumps({"ok": False, "error": status["error"]}, ensure_ascii=False))

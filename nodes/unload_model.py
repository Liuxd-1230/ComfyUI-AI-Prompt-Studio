"""节点 10：Unload LM Studio Model —— 专用 LM Studio 模型卸载节点。

与 Runtime Control 节点共用 services/runtime/control.run_runtime_action
（同一服务层，避免两处实现漂移；Settings /runtime 路由也走同一入口）。
固定 backend=lmstudio，调用官方 POST /api/v1/models/unload（请求体 instance_id，
由 LMStudioBackend.unload 自动从缓存或 v1 loaded_instances[].id 反查）。
只操作独立运行的 LM Studio 服务，不把模型加载进 ComfyUI 进程；用于释放显存给
图像/视频模型。
"""
from __future__ import annotations

import json

from ..services.runtime.control import run_runtime_action
from ..services.runtime.lmstudio import LMStudioBackend


class APS_UnloadModel:
    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {"required": {
            "model": ("STRING", {"default": "", "multiline": False,
                                 "tooltip": "要卸载的模型 key；留空会卸载 LM Studio 当前全部已加载模型"}),
        }, "optional": {
            "prompt": ("STRING", {"forceInput": True,
                                    "tooltip": "可选：把 LLM 文本输出连到这里；卸载完成后原样输出。旧工作流可不连接并独立执行"}),
            "url": ("STRING", {"default": "", "multiline": False,
                               "tooltip": f"本机 LM Studio 通常留空；默认连接 {LMStudioBackend.default_url}"}),
        }}

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("prompt", "result", "status")
    FUNCTION = "unload"
    OUTPUT_NODE = True
    CATEGORY = "AI Prompt Studio"
    DESCRIPTION = ("连接顺序：LLM 提示词输出 → 本节点 prompt → 图像/视频节点 prompt。"
                   "本节点先卸载 LM Studio 模型，再原样传出提示词，给后续步骤释放显存。")

    @classmethod
    def IS_CHANGED(cls, model: str, prompt: str = "", url: str = "") -> float:
        """卸载是外部副作用；每次排队都必须重新执行，不能复用缓存。"""
        return float("nan")

    def unload(self, model: str, prompt: str = "", url: str = "") -> tuple[str, str, str]:
        action = "unload" if model.strip() else "unload_all"
        res = run_runtime_action("lmstudio", action, url, model)
        result = res.get("result") or {}
        payload = {
            "ok": bool(res.get("ok")),
            "model": res.get("model", ""),
            "instance_id": result.get("instance_id", ""),
            "instance_ids": result.get("instance_ids", []),
            "unloaded": res.get("unloaded", result.get("unloaded", [])),
            "error": res.get("error", ""),
        }
        result_json = json.dumps(payload, ensure_ascii=False)
        if not payload["ok"]:
            # 这是显存交接屏障，不是状态展示节点。卸载失败时若仍把 prompt
            # 传给下游，图像/视频模型会在显存未释放时继续加载。
            raise RuntimeError(f"LM Studio 卸载失败：{payload['error'] or result_json}")
        if payload["model"]:
            status = f"已卸载 {payload['model']}"
        else:
            status = f"已卸载 {len(payload['unloaded'])} 个已加载模型"
        return (prompt, result_json, status)

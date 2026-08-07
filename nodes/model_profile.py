"""节点 1：AI Model Profile —— 选择配置档案并输出 AI_PROFILE。

不调用模型，不保存密钥；密钥永远不进节点数据（见 schemas/profile.py node_payload）。
"""

from ..schemas import types
from ..schemas.profile import PROTOCOLS, REASONING_LEVELS, UNLOAD_POLICIES, WEB_SEARCH_POLICIES
from ._helpers import resolve_profile


class APS_ModelProfile:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "profile": ("STRING", {"default": "", "multiline": False,
                                   "tooltip": "AI Prompt Studio 设置面板中创建的档案 ID；留空使用默认档案"}),
            "model_override": ("STRING", {"default": "", "multiline": False,
                                          "tooltip": "覆盖模型名；留空使用档案默认（如 deepseek-v4-flash）"}),
            "protocol": (PROTOCOLS, {"default": "auto",
                                     "tooltip": "auto=按档案/能力决定；responses=DeepSeek Responses API；chat_completions=Chat Completions"}),
            "reasoning": (REASONING_LEVELS, {"default": "high",
                                             "tooltip": "推理强度：off/low/medium/high（映射到各协议的实际参数）"}),
            "web_search": (WEB_SEARCH_POLICIES, {"default": "auto",
                                                 "tooltip": "联网策略：off 关闭；auto 仅在请求时按需；always 强制联网"}),
            "unload_policy": (UNLOAD_POLICIES, {"default": "never",
                                                "tooltip": "本地模型卸载策略：never/请求后/成功后"}),
        }}

    RETURN_TYPES = (types.AI_PROFILE,)
    RETURN_NAMES = ("AI_PROFILE",)
    FUNCTION = "resolve"
    CATEGORY = "AI Prompt Studio"
    DESCRIPTION = "从设置工作台选择配置档案并输出 AI_PROFILE（不调用模型，不含密钥）。"

    def resolve(self, profile, model_override, protocol, reasoning, web_search, unload_policy):
        prof = resolve_profile(profile)
        if model_override and model_override.strip():
            prof.model = model_override.strip()
        if protocol != "auto":
            prof.protocol = protocol
        prof.reasoning = reasoning
        prof.web_search = web_search
        prof.unload_policy = unload_policy
        return (prof.node_payload(),)

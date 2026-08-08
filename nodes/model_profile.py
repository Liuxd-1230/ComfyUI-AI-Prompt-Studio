"""节点 1：AI Model Profile —— 选择配置档案并输出 AI_PROFILE。

不调用模型，不保存密钥；密钥永远不进节点数据（见 schemas/profile.py node_payload）。
"""

import re

from ..schemas import types
from ..schemas.profile import PROTOCOLS, REASONING_LEVELS, UNLOAD_POLICIES, WEB_SEARCH_POLICIES
from ._helpers import resolve_profile


def _profile_and_model_choices() -> tuple[list[str], list[str]]:
    """Read current settings for Comfy combo widgets; failures keep node loadable."""
    profiles = [""]
    models = [""]
    try:
        from ..server.config_store import get_store

        store = get_store()
        for item in store.list_profiles():
            profile_id = str(item.get("profile_id", "")).strip()
            name = str(item.get("name", "")).strip()
            choice = f"{name} [{profile_id}]" if name and name != profile_id else profile_id
            if profile_id and choice not in profiles:
                profiles.append(choice)
            model = str(item.get("model", "")).strip()
            if model and model not in models:
                models.append(model)
            for discovered in store.get_capabilities(profile_id).get("models", []):
                discovered = str(discovered).strip()
                if discovered and discovered not in models:
                    models.append(discovered)
    except Exception:  # noqa: BLE001 - object_info 不能因配置损坏而失败
        pass
    return profiles, models


def _profile_id_from_choice(value: str) -> str:
    """UI 显示名称，节点载荷仍使用稳定 profile_id；兼容旧工作流的裸 ID。"""
    text = str(value or "").strip()
    match = re.search(r"\[([^\[\]]+)\]\s*$", text)
    return match.group(1).strip() if match else text


class APS_ModelProfile:
    @classmethod
    def INPUT_TYPES(cls):
        profiles, models = _profile_and_model_choices()
        return {"required": {
            "profile": (profiles, {"default": "",
                                   "tooltip": "从设置工作台创建的档案中选择；留空使用默认档案"}),
            "model_override": (models, {"default": "",
                                          "tooltip": "覆盖模型名；留空使用档案默认（如 deepseek-v4-flash）"}),
            "protocol": (PROTOCOLS, {"default": "auto",
                                     "tooltip": "auto=按档案/能力决定；responses=DeepSeek Responses API；chat_completions=Chat Completions"}),
            "reasoning": (REASONING_LEVELS, {"default": "high",
                                             "tooltip": "推理强度：off/low/medium/high（映射到各协议的实际参数）"}),
            "web_search": (WEB_SEARCH_POLICIES, {"default": "auto",
                                                 "tooltip": "联网策略：off 关闭；auto 仅在请求时按需；always 强制联网"}),
            "unload_policy": (UNLOAD_POLICIES, {"default": "never",
                                                "tooltip": "本地模型卸载策略：never/请求后/成功后"}),
        }, "optional": {
            "custom_model_override": ("STRING", {"default": "", "multiline": False,
                                                    "tooltip": "仅当下拉中没有目标模型时手动填写；优先级高于模型下拉"}),
        }}

    RETURN_TYPES = (types.AI_PROFILE,)
    RETURN_NAMES = ("AI_PROFILE",)
    FUNCTION = "resolve"
    CATEGORY = "AI Prompt Studio"
    DESCRIPTION = "从设置工作台选择配置档案并输出 AI_PROFILE（不调用模型，不含密钥）。"

    def resolve(self, profile, model_override, protocol, reasoning, web_search, unload_policy,
                custom_model_override=""):
        prof = resolve_profile(_profile_id_from_choice(profile))
        selected_model = (custom_model_override or "").strip() or (model_override or "").strip()
        if selected_model:
            prof.model = selected_model
        if protocol != "auto":
            prof.protocol = protocol
        prof.reasoning = reasoning
        prof.web_search = web_search
        prof.unload_policy = unload_policy
        return (prof.node_payload(),)

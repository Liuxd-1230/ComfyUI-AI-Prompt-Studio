"""节点之间传递的自定义数据类型名（ComfyUI 的 RETURN_TYPES/INPUT_TYPES 用这些字符串）。"""
from __future__ import annotations

import importlib

AI_PROFILE = "AI_PROFILE"
LLM_RESULT = "LLM_RESULT"
CHAT_SESSION = "CHAT_SESSION"
REFERENCE_ANALYSIS = "REFERENCE_ANALYSIS"
CHARACTER_CANDIDATE = "CHARACTER_CANDIDATE"
REFERENCE_MANIFEST = "REFERENCE_MANIFEST"
CHARACTER_BIBLE = "CHARACTER_BIBLE"
CHARACTER_BOOK = "CHARACTER_BOOK"
STORYBOARD = "STORYBOARD"
STORY_ITEM = "STORY_ITEM"
STORY_ITEM_LIST = "STORY_ITEM_LIST"
PROMPT_PLAN = "PROMPT_PLAN"
GENERATION_PROFILE = "GENERATION_PROFILE"
H3_PROMPT_PLAN = "H3_PROMPT_PLAN"

# 类型名 → Schema 类（相对 schemas 包的模块名 + 类名；延迟导入避免环）
_SCHEMA_IMPORTS = {
    AI_PROFILE: (".profile", "AIProfile"),
    LLM_RESULT: (".results", "LLMResult"),
    CHAT_SESSION: (".results", "ChatSession"),
    REFERENCE_ANALYSIS: (".references", "ReferenceAnalysis"),
    CHARACTER_CANDIDATE: (".character", "CharacterCandidate"),
    REFERENCE_MANIFEST: (".references", "ReferenceManifest"),
    CHARACTER_BIBLE: (".character", "CharacterBible"),
    CHARACTER_BOOK: (".character", "CharacterBook"),
    STORYBOARD: (".storyboard", "Storyboard"),
    STORY_ITEM: (".storyboard", "StoryItem"),
    STORY_ITEM_LIST: (".storyboard", "StoryItemList"),
    PROMPT_PLAN: (".prompt_plan", "PromptPlan"),
    GENERATION_PROFILE: (".prompt_plan", "GenerationProfile"),
    H3_PROMPT_PLAN: (".h3", "H3PromptPlan"),
}

_SCHEMA_CACHE: dict[str, type] = {}


def schema_class_for(type_name: str):
    """按类型名解析 Schema 类；未知类型返回 None。

    用 importlib + 相对包名解析，保证返回的类与调用方位于同一棵模块树
    （测试环境存在多棵加载树：aps_extension_test.* / ai_prompt_studio_runtime.*）。
    """
    if type_name in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[type_name]
    entry = _SCHEMA_IMPORTS.get(type_name)
    if not entry:
        return None
    module_name, attr = entry
    try:
        module = importlib.import_module(module_name, package=__package__)
        cls = getattr(module, attr)
    except Exception:  # noqa: BLE001 - 类型名解析失败不应影响节点加载
        return None
    _SCHEMA_CACHE[type_name] = cls
    return cls

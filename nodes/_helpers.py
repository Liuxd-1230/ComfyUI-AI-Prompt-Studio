"""节点公共辅助。"""
from __future__ import annotations

import re
from typing import Any

from ..schemas.profile import AIProfile
from ..server.config_store import get_store


def resolve_profile(profile_id: str) -> AIProfile:
    """按 profile_id 解析档案；空 id 用默认档案；找不到抛可读错误。"""
    store = get_store()
    if profile_id:
        profile = store.get_profile(profile_id)
        if profile is None:
            raise ValueError(
                f"档案不存在: {profile_id!r}。请在 AI Prompt Studio 设置面板创建该档案，"
                "或在节点中留空使用默认档案。"
            )
        return profile
    profile = store.get_default_profile()
    if profile is None:
        raise ValueError(
            "未配置任何档案。请先在 AI Prompt Studio 设置面板创建 profile 并填写 API Key。"
        )
    return profile


def resolve_profile_input(payload: Any) -> AIProfile:
    """解析节点传入档案，并保留 Model Profile 节点允许的运行时覆盖。"""
    incoming = AIProfile.from_json(payload or {})
    stored = resolve_profile(incoming.profile_id)
    for field_name in ("model", "protocol", "reasoning", "web_search", "unload_policy"):
        value = getattr(incoming, field_name)
        if value not in (None, ""):
            setattr(stored, field_name, value)
    problems = stored.validate()
    if problems:
        raise ValueError("档案覆盖无效：" + "；".join(problems))
    return stored


def require_api_key(profile: AIProfile) -> str:
    """取档案密钥；缺失抛可读错误。"""
    key = get_store().get_api_key(profile.profile_id)
    if not key:
        raise ValueError(
            f"档案 {profile.profile_id!r} 未配置 API Key。请在 AI Prompt Studio 设置面板填写。"
        )
    return key


def try_api_key(profile: AIProfile) -> str:
    """取档案密钥；缺失返回空串（供「有 API 增强、无 API 降级」的路径使用）。"""
    return get_store().get_api_key(profile.profile_id) or ""


ANCHOR_STOPWORDS = {"a", "an", "the", "with", "and", "of", "in", "on", "for"}


def identity_anchor_covered(anchor: str, prompt: str) -> bool:
    """锚点的每个实义词都必须按序出现，只容忍标点/连字符漂移与自然词插入。

    刻意比模糊相似度更严：颜色、方位、长度与特征名词仍必须命中。图像与 H3
    两个 Studio 共用这一份实现，只有「角色显示名算不算硬锚点」的策略不同。
    """
    anchor_tokens = [token for token in re.findall(r"[a-z0-9]+", anchor.casefold())
                     if token not in ANCHOR_STOPWORDS]
    if not anchor_tokens:
        return anchor.casefold() in prompt.casefold()
    prompt_tokens = re.findall(r"[a-z0-9]+", prompt.casefold())
    cursor = 0
    for wanted in anchor_tokens:
        try:
            cursor = prompt_tokens.index(wanted, cursor) + 1
        except ValueError:
            return False
    return True

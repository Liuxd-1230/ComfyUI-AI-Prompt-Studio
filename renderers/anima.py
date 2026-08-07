"""ANIMA 提示词渲染器（官方档案，docs/research.md §3）。

三套档案：
- base：官方前缀 `masterpiece, best quality, score_7, safe, ` + 官方负面（含 score_1..3）；
- aesthetic：官方明确建议正负都不用 score_*；保留人类式品质词；
- turbo：官方未给 score 指导（社区传言不采用）→ 人类式品质词，无 score；CFG 1 / 8-12 步。
规范：小写标签、标签间空格（score 标签是唯一带下划线的）、@艺术家、分段排序、
去重、safe/sensitive 开关、tags/natural/hybrid 三模式、Bible 补全、LoRA 触发词。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..schemas.character import CharacterBible
from ..schemas.prompt_plan import GenerationProfile

# ---------------------------------------------------------------- 官方档案
ANIMA_BASE_PREFIX = "masterpiece, best quality, score_7, safe, "
ANIMA_BASE_NEGATIVE = ("worst quality, low quality, score_1, score_2, score_3, "
                       "artist name, blurry, jpeg artifacts, chromatic aberration")
ANIMA_QUALITY_NEGATIVE = ("worst quality, low quality, artist name, blurry, "
                          "jpeg artifacts, chromatic aberration")

QUALITY_TAGS = {"masterpiece", "best quality", "good quality", "normal quality",
                "low quality", "worst quality"} | {f"score_{i}" for i in range(1, 10)}
SAFETY_TAGS = {"safe", "sensitive", "nsfw", "explicit"}
META_TAGS = {"highres", "absurdres", "anime screenshot", "jpeg artifacts",
             "official art", "newest", "recent", "mid", "early", "old"}
COUNT_RE = re.compile(r"^\d+(girl|boy|other)s?$")
YEAR_RE = re.compile(r"^year \d{4}$")

PROFILE_SETTINGS = {
    "base": {"steps": 40, "cfg": 5.0, "sampler": "", "scheduler": ""},
    "aesthetic": {"steps": 40, "cfg": 4.5, "sampler": "", "scheduler": ""},
    "turbo": {"steps": 10, "cfg": 1.0, "sampler": "", "scheduler": ""},
}


@dataclass
class AnimaRenderResult:
    positive: str = ""
    negative: str = ""
    tags: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    profile: GenerationProfile = field(default_factory=GenerationProfile)


# ---------------------------------------------------------------- 工具

def split_tags(text: str) -> List[str]:
    """按逗号切分并归一化（小写、去空白、去空、去重保序）。"""
    seen = []
    for raw in re.split(r"[,\n]+", text or ""):
        tag = raw.strip().lower()
        if tag and tag not in seen:
            seen.append(tag)
    return seen


def is_score_tag(tag: str) -> bool:
    return tag in QUALITY_TAGS and tag.startswith("score_")


def has_underscore_besides_score(tag: str) -> bool:
    return "_" in tag and not tag.startswith("score_")


def classify(tag: str) -> str:
    """按官方顺序分段：quality / meta_year / safety / count / artist / general。"""
    if tag in SAFETY_TAGS:
        return "safety"
    if tag in QUALITY_TAGS or (tag.startswith("score_") and tag in QUALITY_TAGS):
        return "quality"
    if tag in META_TAGS or YEAR_RE.match(tag) or tag in ("newest", "recent", "mid", "early", "old"):
        return "meta_year"
    if COUNT_RE.match(tag):
        return "count"
    if tag.startswith("@"):
        return "artist"
    return "general"


SEGMENT_ORDER = ["quality", "meta_year", "safety", "count", "artist", "general"]


def order_tags(tags: List[str]) -> List[str]:
    """按官方标签顺序排序（段内保持输入顺序）。"""
    buckets: Dict[str, List[str]] = {k: [] for k in SEGMENT_ORDER}
    for t in tags:
        buckets[classify(t)].append(t)
    out: List[str] = []
    for seg in SEGMENT_ORDER:
        out.extend(buckets[seg])
    return out


def _normalize_underscores(tags: List[str]) -> List[str]:
    """把非 score 标签里的下划线转空格（官方规范：只有 score_* 带下划线）。"""
    return [t.replace("_", " ") if has_underscore_besides_score(t) else t for t in tags]


# ---------------------------------------------------------------- 渲染

def render_anima(
    text: str,
    *,
    variant: str = "base",
    prompt_mode: str = "tags",
    content_tier: str = "safe",
    bible: Optional[CharacterBible] = None,
    negative_override: str = "",
    lora_triggers: Optional[List[str]] = None,
) -> AnimaRenderResult:
    """把自由文本/分镜文本渲染为 ANIMA 正负提示词。"""
    if variant not in PROFILE_SETTINGS:
        raise ValueError(f"未知 ANIMA 变体 {variant!r}（可选：base/aesthetic/turbo）")
    if prompt_mode not in ("tags", "natural_language", "hybrid"):
        raise ValueError(f"未知 prompt_mode {prompt_mode!r}")

    result = AnimaRenderResult()
    profile = GenerationProfile(target_family="anima", target_variant=variant,
                                **PROFILE_SETTINGS[variant])
    result.profile = profile

    # 前缀（safe/sensitive 开关 + 变体差异）
    tier = "safe" if content_tier in ("safe", "sensitive") else content_tier
    if content_tier == "sensitive":
        tier = "sensitive"
    if variant == "base":
        prefix = f"masterpiece, best quality, score_7, {tier}, "
    else:
        prefix = f"masterpiece, best quality, {tier}, "

    # Bible 补全（稳定特征作为 character 段）
    bible_tags: List[str] = []
    if bible is not None and bible.character_prompt():
        bible_tags = split_tags(bible.character_prompt())

    # 输入文本
    user_tags = split_tags(text)

    # LoRA 触发词：保持原样（模型专属触发词，不规范化/不重排），追加到末尾
    lora = [t.strip() for t in (lora_triggers or []) if t and t.strip()]

    pre_norm = bible_tags + user_tags  # 规范化前（用于下划线警告）
    merged = _normalize_underscores(bible_tags + user_tags) + lora

    # 去重（Bible 与输入重复时保留一次；LoRA 不去重）
    seen: List[str] = []
    for t in merged:
        if t not in seen:
            seen.append(t)
    ordered = order_tags(seen[:len(seen) - len(lora)] if lora else seen)
    if lora:
        ordered = ordered + lora

    negative = (negative_override.strip() if negative_override and negative_override.strip()
                else (ANIMA_BASE_NEGATIVE if variant == "base" else ANIMA_QUALITY_NEGATIVE))

    if prompt_mode == "tags":
        positive = prefix + ", ".join(ordered)
    else:
        # natural_language / hybrid：文本原样放后面，前缀 + 标签追加
        body = text.strip()
        positive = prefix + (body if body else ", ".join(ordered))
        if prompt_mode == "hybrid" and ordered and body:
            positive = prefix + body.rstrip(", ") + ", " + ", ".join(ordered)

    result.positive = positive
    result.negative = negative
    result.tags = ordered

    # 渲染期警告
    if variant == "aesthetic" and any(t.startswith("score_") for t in ordered):
        result.warnings.append("Aesthetic 官方建议不使用 score_* 标签（已按官方档案保留输入原样，可手动移除）")
    if any(has_underscore_besides_score(t) for t in pre_norm):
        result.warnings.append("检测到下划线标签（官方规范：标签间用空格，仅 score_* 允许下划线）——已自动转换")
    if content_tier not in ("safe", "sensitive"):
        result.warnings.append(f"content_tier={content_tier!r} 未知，回退 safe")
    return result

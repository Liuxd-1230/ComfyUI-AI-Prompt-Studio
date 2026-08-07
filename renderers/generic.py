"""通用图像模型渲染器（generic_image / sdxl / flux_kontext）。

仅做确定性整理（去重、大小写规范、正负拆分），不做官方档案级处理
（各模型没有统一官方规范；ANIMA 专属规则在 renderers/anima.py）。
0.2.1a：CharacterBook 传入时渲染**全部**人物（不再只取第一个档案）。
"""
from __future__ import annotations

from typing import List, Optional

from ..schemas.character import CharacterBible, CharacterBook
from ..schemas.prompt_plan import GenerationProfile

FAMILY_PROFILES = {
    "generic_image": GenerationProfile(target_family="generic_image",
                                       steps=30, cfg=5.0),
    "sdxl": GenerationProfile(target_family="sdxl", steps=30, cfg=6.5,
                              sampler="euler_ancestral", resolution="1024x1024"),
    "flux": GenerationProfile(target_family="flux", steps=28, cfg=1.0,
                              sampler="euler", scheduler="simple"),
}


def render_generic(
    text: str,
    *,
    family: str = "generic_image",
    variant: str = "",
    prompt_mode: str = "tags",
    bible: Optional[CharacterBible] = None,
    book: Optional[CharacterBook] = None,
    negative_override: str = "",
) -> dict:
    """返回 {positive, negative, tags, warnings, profile}。

    book（CharacterBook）优先：渲染容器内全部人物；bible 作为单人物兼容路径。
    """
    profile = (FAMILY_PROFILES.get(family) or
               GenerationProfile(target_family=family, target_variant=variant))
    if variant and family in FAMILY_PROFILES:
        profile = GenerationProfile(target_family=family, target_variant=variant,
                                    **{k: v for k, v in FAMILY_PROFILES[family].to_json().items()
                                       if k not in ("target_family", "target_variant", "extra")})

    warnings: List[str] = []
    parts: List[str] = []
    # 0.2.1a：CharacterBook → 全部人物特征；单人物 bible 兜底
    char_sources: List[CharacterBible] = []
    if book is not None and book.characters:
        char_sources = list(book.characters)
    elif bible is not None:
        char_sources = [bible]
    for b in char_sources:
        cp = b.character_prompt()
        if cp:
            parts.extend(p.strip() for p in cp.split(",") if p.strip())
    parts.extend(p.strip() for p in (text or "").split(",") if p.strip())

    seen: List[str] = []
    for p in parts:
        if p not in seen:
            seen.append(p)

    if prompt_mode == "natural_language":
        # 0.2.1b：Natural 模式也消费 CharacterBook——人物特征拼成自然语句，
        # 而不是 tag soup；正文已含的特征不再重复。
        positive = _natural_with_characters(text, char_sources)
    elif prompt_mode == "hybrid":
        # 少量补充分隔标签 + 正文；正文已含的不再重复追加
        body = text.strip()
        extra = [p for p in seen if p and p.lower() not in body.lower()]
        positive = body + (", " + ", ".join(extra) if extra else "")
    else:
        positive = ", ".join(seen)

    negative = negative_override.strip() or ""
    return {"positive": positive, "negative": negative, "tags": seen,
            "warnings": warnings, "profile": profile}


def _natural_with_characters(body: str, char_sources: List[CharacterBible]) -> str:
    """把人物档案拼成自然语言描述，追加到正文前。

    格式（示例）：
      "A, with black short hair and a white military uniform. B, with long blonde hair and a black dress. A holds B's hand."
    - 每人物一句；多个特征用 and 连接；人物无名字时用 "the character"；
    - 特征值已在正文中出现（子串）则跳过，避免重复；
    - 无人物信息时原样返回正文（与旧行为一致）。
    """
    body = body.strip()
    clauses: List[str] = []
    for b in char_sources:
        name = (b.name or "").strip() or "the character"
        attrs = [t.value.strip() for t in b.traits
                 if t.category != "uncertain" and t.value.strip()
                 and t.value.strip().lower() not in body.lower()]
        if not attrs:
            continue
        if len(attrs) == 1:
            clause = f"{name}, with {attrs[0]}"
        else:
            clause = f"{name}, with {' and '.join(attrs[:-1])} and {attrs[-1]}"
        clauses.append(clause)
    if not clauses:
        return body
    head = ". ".join(clauses) + ". "
    return (head + body) if body else head.strip()

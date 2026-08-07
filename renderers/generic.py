"""通用图像模型渲染器（generic_image / sdxl / flux_kontext）。

仅做确定性整理（去重、大小写规范、正负拆分），不做官方档案级处理
（各模型没有统一官方规范；ANIMA 专属规则在 renderers/anima.py）。
"""
from __future__ import annotations

from typing import List, Optional

from ..schemas.character import CharacterBible
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
    negative_override: str = "",
) -> dict:
    """返回 {positive, negative, tags, warnings, profile}。"""
    profile = (FAMILY_PROFILES.get(family) or
               GenerationProfile(target_family=family, target_variant=variant))
    if variant and family in FAMILY_PROFILES:
        profile = GenerationProfile(target_family=family, target_variant=variant,
                                    **{k: v for k, v in FAMILY_PROFILES[family].to_json().items()
                                       if k not in ("target_family", "target_variant", "extra")})

    warnings: List[str] = []
    parts: List[str] = []
    if bible is not None and bible.character_prompt():
        parts.extend(p.strip() for p in bible.character_prompt().split(",") if p.strip())
    parts.extend(p.strip() for p in (text or "").split(",") if p.strip())

    seen: List[str] = []
    for p in parts:
        if p not in seen:
            seen.append(p)

    if prompt_mode == "natural_language":
        positive = text.strip()
    elif prompt_mode == "hybrid":
        positive = text.strip() + (", " + ", ".join(seen) if seen else "")
    else:
        positive = ", ".join(seen)

    negative = negative_override.strip() or ""
    return {"positive": positive, "negative": negative, "tags": seen,
            "warnings": warnings, "profile": profile}

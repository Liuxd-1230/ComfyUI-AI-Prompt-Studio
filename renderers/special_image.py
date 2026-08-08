"""Official-contract renderers for Z-Image Turbo and Qwen-Image-Edit-2511."""
from __future__ import annotations

from typing import List

from ..schemas.prompt_plan import GenerationProfile


def render_special_image(text: str, *, family: str, variant: str = "",
                         negative_override: str = "") -> dict:
    positive = (text or "").strip()
    warnings: List[str] = []
    if negative_override.strip():
        warnings.append("该目标不使用独立负面提示词；negative 输入已忽略。")

    if family == "z_image":
        profile = GenerationProfile(
            target_family=family, target_variant=variant or "turbo",
            steps=9, cfg=0.0,
            notes="Z-Image Turbo：使用完整、具体的自然语言描述；不使用 CFG 负面提示词。",
            extra={"max_sequence_length": 512},
        )
        if len(positive) < 80:
            warnings.append("Z-Image Turbo 通常受益于更长、更具体的主体、环境、构图与光线描述。")
    elif family == "qwen_image_edit":
        profile = GenerationProfile(
            target_family=family, target_variant=variant or "2511",
            notes="Qwen-Image-Edit-2511：明确写出编辑动作、对象和位置；多图用 Figure 1、Figure 2 引用。",
        )
        if "@图" in positive:
            warnings.append("仍有未转换的 @图片引用；请先经过“图片引用提示词”节点。")
    else:
        raise ValueError(f"不支持的专用图像模型: {family}")

    return {"positive": positive, "negative": "", "tags": [],
            "warnings": warnings, "profile": profile}

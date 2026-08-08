"""图片引用提示词：把 @图N 转成目标模型可识别的引用，并生成资产清单。"""
from __future__ import annotations

from typing import Any, Optional

from ..schemas import types
from ..schemas.references import AssetRef, ReferenceManifest

TARGETS = ["qwen_image_edit_2511", "minimax_h3", "generic"]


class APS_ReferencePrompt:
    @classmethod
    def INPUT_TYPES(cls) -> dict[str, dict[str, tuple]]:
        return {
            "required": {
                "prompt": ("STRING", {
                    "default": "让@图1中的角色采用@图2的服装，保持人物身份不变。",
                    "multiline": True,
                    "tooltip": "在输入框键入 @，可选择已连接图片。",
                }),
                "target": (TARGETS, {"default": "qwen_image_edit_2511"}),
            },
            "optional": {
                "image_1": ("IMAGE",),
                "image_2": ("IMAGE",),
                "image_3": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("STRING", types.REFERENCE_MANIFEST, "STRING", "INT")
    RETURN_NAMES = ("prompt", "REFERENCE_MANIFEST", "references", "count")
    FUNCTION = "build"
    CATEGORY = "AI Prompt Studio"
    DESCRIPTION = "输入 @ 选择已连接图片；按 Qwen Figure N 或 MiniMax <Picture N> 格式输出。"

    def build(self, prompt: str, target: str,
              image_1: Optional[Any] = None,
              image_2: Optional[Any] = None,
              image_3: Optional[Any] = None) -> tuple[str, dict, str, int]:
        images = (image_1, image_2, image_3)
        manifest = ReferenceManifest(notes=f"由图片引用提示词节点生成；target={target}")
        labels: list[str] = []
        rendered = prompt.strip()
        logical_index = 0
        for slot_index, image in enumerate(images, start=1):
            token = f"@图{slot_index}"
            if image is None:
                if token in rendered:
                    raise ValueError(f"提示词使用了 {token}，但 image_{slot_index} 未连接")
                continue
            if token not in rendered:
                continue
            logical_index += 1
            label = _target_label(target, logical_index)
            rendered = rendered.replace(token, label)
            labels.append(f"图{slot_index} → {label}")
            manifest.add_asset(AssetRef(
                asset_id=f"image_{slot_index}", asset_type="image",
                data_ref=f"image_{slot_index}",
                h3_labels=[f"Picture {logical_index}"],
                source="APS_ReferencePrompt", note=label,
            ))
        return rendered, manifest.to_json(), "\n".join(labels) or "未连接图片", len(labels)


def _target_label(target: str, index: int) -> str:
    if target == "qwen_image_edit_2511":
        return f"Figure {index}"
    if target == "minimax_h3":
        return f"<Picture {index}>"
    return f"Image {index}"

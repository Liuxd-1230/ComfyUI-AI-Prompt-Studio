"""节点 8：MiniMax H3 Prompt Director —— 生成/改写/转换/审计/修复 H3 提示词。

流程（docs/adr/0004-deterministic-h3-rendering.md）：
LLM 产出结构化计划（内容决策）→ Python renderer 确定性拼装最终格式 →
validator 校验（官方手册规则）→ 可选 repair 循环。
输出 STRING 直连 ComfyUI 核心 H3 节点（已验证）。
"""
from __future__ import annotations

from typing import Any, Optional

from ..schemas import types
from ..schemas.character import CharacterBible
from ..schemas.h3 import H3_MODES, H3_OPERATIONS, H3PromptPlan
from ..schemas.profile import AIProfile
from ..schemas.references import ReferenceManifest
from ..schemas.storyboard import Storyboard
from ..renderers.minimax_h3 import render_h3
from ..services.gateway import Gateway, GenerateRequest
from ..services.h3_plan import (
    build_plan_prompt,
    convert_storyboard,
    map_image_assets,
    parse_plan_json,
)
from ..validators.minimax_h3 import validate_h3
from ._helpers import require_api_key, resolve_profile


class APS_MiniMaxH3Director:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "AI_PROFILE": (types.AI_PROFILE,),
            "text": ("STRING", {"default": "", "multiline": True,
                                "tooltip": "剧情/画面/声音描述（R2V 模式为需要重写的参考视频描述）"}),
            "mode": (H3_MODES, {"default": "T2VA",
                                "tooltip": "T2VA=纯文本；I2VA=首帧锚定；FL2VA=首尾帧路径；L2VA=尾帧收敛；R2V=全参考重写"}),
            "operation": (H3_OPERATIONS, {"default": "generate",
                                          "tooltip": "generate=生成；rewrite=改写；convert_storyboard=分镜转换；audit=审计；repair=修复"}),
            "duration": ("FLOAT", {"default": 10.0, "min": 0.5, "max": 600.0,
                                   "tooltip": "目标视频时长（秒），决定首行对齐指令的 S.SS 与镜头时间戳"}),
        }, "optional": {
            "storyboard": (types.STORYBOARD,),
            "character_bible": (types.CHARACTER_BIBLE,),
            "reference_manifest": (types.REFERENCE_MANIFEST,),
            "images": ("IMAGE", {"tooltip": "首/尾帧参考图（I2VA/FL2VA/L2VA 使用，按位置映射为 Picture 资产）"}),
        }}

    RETURN_TYPES = ("STRING", types.H3_PROMPT_PLAN, types.REFERENCE_MANIFEST, "STRING", "STRING")
    RETURN_NAMES = ("prompt", "H3_PROMPT_PLAN", "REFERENCE_MANIFEST", "validation", "warnings")
    FUNCTION = "direct"
    CATEGORY = "AI Prompt Studio"
    DESCRIPTION = "按官方手册生成/改写/转换/审计/修复 MiniMax H3 提示词（输出 STRING 直连核心 H3 节点）。"

    def direct(self, AI_PROFILE, text, mode, operation, duration,
               storyboard=None, character_bible=None, reference_manifest=None,
               images=None):
        profile = AIProfile.from_json(AI_PROFILE or {})
        if not profile.profile_id:
            raise ValueError("未收到 AI_PROFILE：请先连接 AI Model Profile 节点")
        prof = resolve_profile(profile.profile_id)
        api_key = require_api_key(prof)

        manifest = (ReferenceManifest.from_json(reference_manifest)
                    if reference_manifest else ReferenceManifest())
        bible = CharacterBible.from_json(character_bible) if character_bible else None
        sb = Storyboard.from_json(storyboard) if storyboard else None
        img_count = _count_images(images)

        # ------------------------------------------------------------ audit
        if operation == "audit":
            if not text or not text.strip():
                raise ValueError("audit 需要把已有 H3 提示词输入到 text")
            report = validate_h3(text, mode)
            plan = H3PromptPlan(mode=mode, operation="audit",
                                duration_seconds=duration, validation=report)
            return (text, plan.to_json(), manifest.to_json(),
                    report.as_text(), "")

        # ------------------------------------------------------------ 内容输入
        if operation == "convert_storyboard" and sb is None:
            raise ValueError("convert_storyboard 需要连接 STORYBOARD 输入")
        if operation != "convert_storyboard" and (not text or not text.strip()):
            raise ValueError("text 为空：generate/rewrite/repair 需要剧情/画面描述")

        repair_issues = ""
        if operation == "repair":
            if not text or not text.strip():
                raise ValueError("repair 需要把已有提示词输入到 text")
            repair_issues = validate_h3(text, mode).as_text()

        # ------------------------------------------------------------ LLM 计划
        prompt = build_plan_prompt(
            text.strip() if text else "", mode, float(duration or 1.0),
            storyboard=sb, bible=bible, manifest=manifest, image_count=img_count,
            repair_issues=repair_issues)
        req = GenerateRequest(
            system="You are a MiniMax H3 prompt specialist. Output only JSON.",
            messages=[_msg(prompt)], web_search="off", reasoning="high",
            max_tokens=8192, timeout=prof.timeout)
        result = Gateway().generate(prof, api_key, req)
        if result.has_error():
            raise ValueError(result.error.as_text)

        # ------------------------------------------------------------ 解析/回退
        try:
            plan = parse_plan_json(result.text, mode, float(duration or 1.0))
            if not plan.shots and sb is not None:
                plan = convert_storyboard(sb, mode, float(duration or 1.0), manifest)
                plan.raw = result.text
                plan.warnings.append("LLM 未返回镜头，已回退为分镜结构转换（描述沿用分镜文本）")
        except ValueError as exc:
            if sb is not None:
                plan = convert_storyboard(sb, mode, float(duration or 1.0), manifest)
                plan.warnings.append(f"计划解析失败，已回退分镜转换：{exc}")
            else:
                raise
        if sb is not None and operation == "convert_storyboard":
            plan.storyboard_id = sb.story_id

        map_image_assets(plan, img_count, mode)

        # ------------------------------------------------------------ 渲染 + 校验
        rendered = render_h3(plan)
        report = validate_h3(rendered, mode)
        plan.validation = report
        return (rendered, plan.to_json(), manifest.to_json(),
                report.as_text(), "\n".join(plan.warnings))


def _count_images(images: Any) -> int:
    if images is None:
        return 0
    if hasattr(images, "shape"):
        shape = images.shape
        if len(shape) >= 3:
            return int(shape[0])
        return 1
    if isinstance(images, (list, tuple)):
        return len(images)
    return 1


def _msg(content: str):
    from ..schemas.results import ChatMessage

    return ChatMessage(role="user", content=content)

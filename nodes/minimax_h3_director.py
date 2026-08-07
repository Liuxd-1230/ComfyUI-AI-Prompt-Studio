"""节点 8：MiniMax H3 Prompt Director —— 生成/改写/转换/审计/修复 H3 提示词。

流程（docs/adr/0004-deterministic-h3-rendering.md）：
LLM 产出结构化计划（内容决策）→ Python renderer 确定性拼装最终格式（含媒体
独立编号 normalize_media_labels）→ validator 校验（官方手册规则）→
可选一次语义修复（auto_repair，含 R2V 英文翻译修复）→ 再次渲染+校验。
输出 STRING 直连 ComfyUI 核心 H3 节点（已验证）。
"""
from __future__ import annotations

from typing import Any, List, Optional

from ..schemas import types
from ..schemas.character import CharacterBible, CharacterBook
from ..schemas.h3 import H3_MODES, H3_OPERATIONS, H3PromptPlan
from ..schemas.profile import AIProfile
from ..schemas.references import ReferenceManifest
from ..schemas.storyboard import Storyboard
from ..renderers.minimax_h3 import render_h3
from ..services.gateway import Gateway, GenerateRequest
from ..services.h3_plan import (
    H3_SYSTEM_PROMPT,
    build_plan_prompt,
    convert_storyboard,
    map_image_assets,
    normalize_media_labels,
    parse_plan_json,
)
from ..validators.minimax_h3 import r2v_english_issue, validate_h3
from ._helpers import require_api_key, resolve_profile

# 模式资产约束：T2VA=0；I2VA=1（首帧）；FL2VA=2（首尾）；L2VA=1（尾帧）；R2V 不限
MODE_IMAGE_REQUIREMENTS = {"I2VA": 1, "FL2VA": 2, "L2VA": 1}


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
            "auto_repair": ("BOOLEAN", {"default": True,
                                        "tooltip": "校验失败时最多做一次 LLM 语义修复（含 R2V 英文翻译修复）；确定性格式错误由 Python 直接修正，不费 API"}),
        }, "optional": {
            "storyboard": (types.STORYBOARD,),
            "character_bible": (types.CHARACTER_BIBLE,),
            "character_book": (types.CHARACTER_BOOK,),
            "reference_manifest": (types.REFERENCE_MANIFEST,),
            "images": ("IMAGE", {"tooltip": "首/尾帧参考图（I2VA/FL2VA/L2VA 使用，按位置映射为 Picture 资产）"}),
        }}

    RETURN_TYPES = ("STRING", types.H3_PROMPT_PLAN, types.REFERENCE_MANIFEST, "STRING", "STRING")
    RETURN_NAMES = ("prompt", "H3_PROMPT_PLAN", "REFERENCE_MANIFEST", "validation", "warnings")
    FUNCTION = "direct"
    CATEGORY = "AI Prompt Studio"
    DESCRIPTION = "按官方手册生成/改写/转换/审计/修复 MiniMax H3 提示词（输出 STRING 直连核心 H3 节点）。"

    def direct(self, AI_PROFILE, text, mode, operation, duration, auto_repair=True,
               storyboard=None, character_bible=None, character_book=None,
               reference_manifest=None, images=None):
        profile = AIProfile.from_json(AI_PROFILE or {})
        if not profile.profile_id:
            raise ValueError("未收到 AI_PROFILE：请先连接 AI Model Profile 节点")
        prof = resolve_profile(profile.profile_id)
        api_key = require_api_key(prof)

        manifest = (ReferenceManifest.from_json(reference_manifest)
                    if reference_manifest else ReferenceManifest())
        book = CharacterBook.from_json(character_book) if character_book else None
        bible = CharacterBible.from_json(character_bible) if character_bible else None
        if bible is None and book is not None:
            bible = book.first_bible()
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
            storyboard=sb, bible=bible, book=book, manifest=manifest,
            image_count=img_count, repair_issues=repair_issues)
        req = GenerateRequest(
            system=H3_SYSTEM_PROMPT,
            messages=[_msg(prompt)], web_search="off", reasoning="high",
            max_tokens=8192, timeout=prof.timeout)
        result = Gateway().generate(prof, api_key, req)
        if result.has_error():
            raise ValueError(result.error.as_text)

        # ------------------------------------------------------------ 解析/回退
        plan = self._parse_plan(result.text, sb, mode, duration, manifest, book)
        if sb is not None and operation == "convert_storyboard":
            plan.storyboard_id = sb.story_id

        # 模式资产约束（不满足则记 error，不生成错误引用）
        plan.warnings.extend(map_image_assets(plan, img_count, mode))

        # 确定性修正：媒体独立编号（不费 API）
        normalize_media_labels(plan)

        rendered = render_h3(plan)
        report = validate_h3(rendered, mode)
        self._apply_mode_asset_errors(report, mode, img_count)

        # ------------------------------------------------------------ 一次自动修复
        if auto_repair and not report.valid or (auto_repair and mode == "R2V"
                                                and r2v_english_issue(rendered)):
            fixed = self._repair_once(prof, api_key, text, mode, duration, report,
                                      sb, bible, book, manifest, img_count)
            if fixed is not None:
                plan, rendered, report = fixed
                plan.warnings.append("已执行一次自动修复（auto_repair）")

        if mode == "R2V" and r2v_english_issue(rendered):
            report.add("error", "h3_r2v_english",
                       "R2V 语义段仍含大量非英语内容（修复后未通过；对白/歌词/画面文字除外）")

        plan.validation = report
        return (rendered, plan.to_json(), manifest.to_json(),
                report.as_text(), "\n".join(plan.warnings))

    # ------------------------------------------------------------ 内部
    def _parse_plan(self, raw, sb, mode, duration, manifest, book):
        try:
            plan = parse_plan_json(raw, mode, float(duration or 1.0))
            if not plan.shots and sb is not None:
                plan = convert_storyboard(sb, mode, float(duration or 1.0), manifest, book)
                plan.raw = raw
                plan.warnings.append("LLM 未返回镜头，已回退为分镜结构转换（描述沿用分镜文本）")
            return plan
        except ValueError as exc:
            if sb is not None:
                plan = convert_storyboard(sb, mode, float(duration or 1.0), manifest, book)
                plan.warnings.append(f"计划解析失败，已回退分镜转换：{exc}")
                return plan
            raise

    def _repair_once(self, prof, api_key, text, mode, duration, report,
                     sb, bible, book, manifest, img_count):
        """最多一次 LLM 语义修复；返回 (plan, rendered, report) 或 None。"""
        prompt = build_plan_prompt(
            text.strip() if text else "", mode, float(duration or 1.0),
            storyboard=sb, bible=bible, book=book, manifest=manifest,
            image_count=img_count, repair_issues=report.as_text())
        req = GenerateRequest(
            system=H3_SYSTEM_PROMPT + "\nFix only the reported issues. "
                   "Preserve all unrelated details, structure, and the user's concept.",
            messages=[_msg(prompt)], web_search="off", reasoning="medium",
            max_tokens=8192, timeout=prof.timeout)
        result = Gateway().generate(prof, api_key, req)
        if result.has_error():
            return None
        try:
            plan = self._parse_plan(result.text, sb, mode, duration, manifest, book)
        except ValueError:
            return None
        plan.warnings.extend(map_image_assets(plan, img_count, mode))
        normalize_media_labels(plan)
        rendered = render_h3(plan)
        report = validate_h3(rendered, mode)
        self._apply_mode_asset_errors(report, mode, img_count)
        return plan, rendered, report

    def _apply_mode_asset_errors(self, report, mode, img_count) -> None:
        need = MODE_IMAGE_REQUIREMENTS.get(mode)
        if need is not None and img_count != need:
            report.add("error", "h3_asset_mode",
                       f"{mode} 需要 {need} 张参考图，实际 {img_count}（该模式不应生成缺失图片的引用）")


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

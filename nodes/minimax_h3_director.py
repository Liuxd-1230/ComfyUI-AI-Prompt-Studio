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
from ..schemas.references import AssetRef, ReferenceManifest
from ..schemas.storyboard import Scene, Shot, Storyboard
from ..renderers.minimax_h3 import render_h3
from ..services.gateway import Gateway, GenerateRequest
from ..services.h3_plan import (
    H3_SCHEMA,
    build_plan_prompt,
    convert_storyboard,
    map_image_assets,
    normalize_media_labels,
    parse_plan_json,
    sync_manifest_assets,
    h3_system_prompt,
)
from ..validators.minimax_h3 import r2v_english_issue, validate_h3
from ._helpers import require_api_key, resolve_profile_input, try_api_key

# 模式资产约束：T2VA=0；I2VA=1（首帧）；FL2VA=2（首尾）；L2VA=1（尾帧）；R2V 不限
MODE_IMAGE_REQUIREMENTS = {"T2VA": 0, "I2VA": 1, "FL2VA": 2, "L2VA": 1}


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
            "duration": ("FLOAT", {"default": 10.0, "min": 4.0, "max": 15.0,
                                   "tooltip": "目标视频时长（秒），决定首行对齐指令的 S.SS 与镜头时间戳"}),
            "auto_repair": ("BOOLEAN", {"default": True,
                                        "tooltip": "校验失败时最多做一次 LLM 语义修复（含 R2V 英文翻译修复）；确定性格式错误由 Python 直接修正，不费 API"}),
        }, "optional": {
            "storyboard": (types.STORYBOARD,),
            "character_bible": (types.CHARACTER_BIBLE,),
            "character_book": (types.CHARACTER_BOOK,),
            "reference_manifest": (types.REFERENCE_MANIFEST,),
            "images": ("IMAGE", {"tooltip": "首/尾帧参考图（I2VA/FL2VA/L2VA 使用，按位置映射为 Picture 资产）"}),
            "video_1": ("VIDEO", {"tooltip": "Ref2VA 视频参考 1（最多 3 个）"}),
            "video_2": ("VIDEO", {"tooltip": "Ref2VA 视频参考 2"}),
            "video_3": ("VIDEO", {"tooltip": "Ref2VA 视频参考 3"}),
            "audio_1": ("AUDIO", {"tooltip": "Ref2VA 音频参考 1（不能作为唯一参考）"}),
            "audio_2": ("AUDIO", {"tooltip": "Ref2VA 音频参考 2"}),
            "audio_3": ("AUDIO", {"tooltip": "Ref2VA 音频参考 3"}),
        }}

    RETURN_TYPES = ("STRING", types.H3_PROMPT_PLAN, types.REFERENCE_MANIFEST, "STRING", "STRING")
    RETURN_NAMES = ("prompt", "H3_PROMPT_PLAN", "REFERENCE_MANIFEST", "validation", "warnings")
    FUNCTION = "direct"
    CATEGORY = "AI Prompt Studio"
    DESCRIPTION = "按官方手册生成/改写/转换/审计/修复 MiniMax H3 提示词（输出 STRING 直连核心 H3 节点）。"

    def direct(self, AI_PROFILE, text, mode, operation, duration, auto_repair=True,
               storyboard=None, character_bible=None, character_book=None,
               reference_manifest=None, images=None, video_1=None, video_2=None,
               video_3=None, audio_1=None, audio_2=None, audio_3=None):
        mode = _normalize_mode(mode)
        if not 4.0 <= float(duration) <= 15.0:
            raise ValueError("MiniMax H3 目标时长必须在 4–15 秒之间")
        profile = AIProfile.from_json(AI_PROFILE or {})
        if not profile.profile_id:
            raise ValueError("未收到 AI_PROFILE：请先连接 AI Model Profile 节点")
        prof = resolve_profile_input(AI_PROFILE)

        manifest = (ReferenceManifest.from_json(reference_manifest)
                    if reference_manifest else ReferenceManifest())
        _register_media_inputs(manifest, "video", (video_1, video_2, video_3))
        _register_media_inputs(manifest, "audio", (audio_1, audio_2, audio_3))
        book = CharacterBook.from_json(character_book) if character_book else None
        bible = CharacterBible.from_json(character_bible) if character_bible else None
        if bible is None and book is not None:
            bible = book.first_bible()
        sb = Storyboard.from_json(storyboard) if storyboard else None
        img_count = _count_images(images)
        _register_image_inputs(manifest, img_count)

        # ------------------------------------------------------------ audit（完全离线，0.2.1）
        if operation == "audit":
            if not text or not text.strip():
                raise ValueError("audit 需要把已有 H3 提示词输入到 text")
            report = validate_h3(text, mode, duration=duration, manifest=manifest)
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
            repair_issues = validate_h3(text, mode, duration=duration,
                                        manifest=manifest).as_text()

        # 职责解耦（0.2.1）：LLM 路径才要求 API Key。
        # convert_storyboard 支持纯 Python 确定性转换（无 API 也可用；有 API 时
        # LLM 增强内容决策）；generate/rewrite/repair 必须有 API。
        api_key = ""
        needs_llm = operation != "convert_storyboard"
        if needs_llm:
            api_key = require_api_key(prof)
        else:
            api_key = try_api_key(prof)
            if api_key:
                needs_llm = True  # 有 API：走 LLM 计划（可增强）

        # ------------------------------------------------------------ LLM 计划
        if needs_llm:
            prompt = build_plan_prompt(
                text.strip() if text else "", mode, float(duration or 1.0),
                storyboard=sb, bible=bible, book=book, manifest=manifest,
                image_count=img_count, repair_issues=repair_issues)
            req = GenerateRequest(
                system=h3_system_prompt(),
                messages=[_msg(prompt)], web_search="off", reasoning="high",
                max_tokens=8192, timeout=prof.timeout,
                # 0.2.1 P1-17：Provider 支持原生 Structured Output → 协议层 schema；
                # 不支持时 Gateway 自动降级为提示词约束（与 build_plan_prompt 的 JSON 模板一致）
                output_schema=H3_SCHEMA)
            result = Gateway().generate(prof, api_key, req)
            if result.has_error():
                raise ValueError(result.error.as_text)
        else:
            # 无 API：确定性分镜转换（画面描述沿用分镜文本，不调用 LLM，不伪造）
            result = None

        # ------------------------------------------------------------ 解析/回退
        if result is not None:
            plan = self._parse_plan(result.text, sb, mode, duration, manifest, book)
        else:
            plan = convert_storyboard(sb, mode, float(duration or 1.0), manifest, book)
            plan.warnings.append("无 API Key：已使用确定性分镜转换（有 API 时可获得更丰富的画面/声音描述）")
        if sb is not None and operation == "convert_storyboard":
            plan.storyboard_id = sb.story_id

        # 模式资产约束（不满足则记 error，不生成错误引用）
        sync_manifest_assets(plan, manifest)
        plan.warnings.extend(map_image_assets(plan, img_count, mode))

        # 确定性修正：媒体独立编号（不费 API）
        normalize_media_labels(plan)

        rendered = render_h3(plan)
        report = validate_h3(rendered, mode, duration=duration, manifest=manifest,
                             plan=plan)
        self._apply_mode_asset_errors(report, mode, img_count)

        # ------------------------------------------------------------ 一次自动修复
        # 无 API（确定性转换路径）不尝试 LLM 修复：确定性格式修正已由
        # normalize_media_labels/render 完成，语义问题保留在报告里（不伪造）。
        if (needs_llm and auto_repair and not report.valid) or (
                needs_llm and auto_repair and mode in {"R2V", "Ref2VA"}
                and r2v_english_issue(rendered)):
            fixed, repair_error = self._repair_once(
                prof, api_key, text, mode, duration, report,
                sb, bible, book, manifest, img_count)
            if fixed is not None:
                plan, rendered, report = fixed
                plan.warnings.append("已执行一次自动修复（auto_repair）")
            else:
                plan.warnings.append(f"自动修复未完成：{repair_error}")

        if mode in {"R2V", "Ref2VA"} and r2v_english_issue(rendered):
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
            # 部分第三方 OpenAI/DeepSeek 代理会接受 json_schema 参数，却仍返回
            # 普通文本。纯文本 generate 没有 Storyboard 时也必须产生可编辑结果，
            # 不能让整个 Comfy 图在解析层崩溃。保留模型原文作为单镜头内容，
            # 再由确定性 renderer/validator 形成完整三字段或六段提示词。
            fallback = Storyboard(
                title="H3 plain-text fallback", summary=str(raw or "").strip(),
                split_mode="shot", scenes=[Scene(
                    scene_id="scene_fallback", index=1, title="Generated scene",
                    shots=[Shot(shot_id="shot_fallback", index=1,
                                summary=str(raw or "").strip(),
                                duration=float(duration or 1.0))])])
            plan = convert_storyboard(fallback, mode, float(duration or 1.0), manifest, book)
            plan.raw = str(raw or "")
            plan.warnings.append(
                f"模型没有返回合法 JSON，已把其普通文本回退为单镜头计划：{exc}")
            return plan

    def _repair_once(self, prof, api_key, text, mode, duration, report,
                     sb, bible, book, manifest, img_count):
        """最多一次 LLM 语义修复；同时返回失败原因，禁止静默吞错。"""
        prompt = build_plan_prompt(
            text.strip() if text else "", mode, float(duration or 1.0),
            storyboard=sb, bible=bible, book=book, manifest=manifest,
            image_count=img_count, repair_issues=report.as_text())
        req = GenerateRequest(
            system=h3_system_prompt() + "\nFix only the reported issues. "
                   "Preserve all unrelated details, structure, and the user's concept.",
            messages=[_msg(prompt)], web_search="off", reasoning="medium",
            max_tokens=8192, timeout=prof.timeout,
            output_schema=H3_SCHEMA)
        result = Gateway().generate(prof, api_key, req)
        if result.has_error():
            return None, (result.error.message if result.error else "模型调用失败")
        try:
            plan = self._parse_plan(result.text, sb, mode, duration, manifest, book)
        except ValueError as exc:
            return None, f"修复结果无法解析：{exc}"
        if sb is not None:
            plan.storyboard_id = sb.story_id
        sync_manifest_assets(plan, manifest)
        plan.warnings.extend(map_image_assets(plan, img_count, mode))
        normalize_media_labels(plan)
        rendered = render_h3(plan)
        report = validate_h3(rendered, mode, duration=duration, manifest=manifest,
                             plan=plan)
        self._apply_mode_asset_errors(report, mode, img_count)
        return (plan, rendered, report), ""

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


def _normalize_mode(mode: str) -> str:
    if mode in {"R2V", "R2V (legacy)"}:
        return "Ref2VA"
    return mode


def _register_media_inputs(manifest: ReferenceManifest, kind: str,
                           values: tuple[Any, ...]) -> None:
    """把 Comfy 媒体连接注册为可审计的 Ref2VA 资产句柄。"""
    existing = {asset.asset_id for asset in manifest.assets}
    for index, value in enumerate(values, start=1):
        if value is None:
            continue
        asset_id = f"{kind}_{index}"
        if asset_id in existing:
            continue
        manifest.add_asset(AssetRef(
            asset_id=asset_id, asset_type=kind,
            data_ref=f"{kind}_{index}", source="APS_MiniMaxH3Director",
            h3_labels=[f"{kind.title()} {index}"],
            note=f"connected {kind} reference {index}",
            time_start=0.0 if _media_duration(value) is not None else None,
            time_end=_media_duration(value),
        ))


def _register_image_inputs(manifest: ReferenceManifest, count: int) -> None:
    existing = {asset.asset_id for asset in manifest.assets}
    for index in range(1, count + 1):
        asset_id = f"image_{index}"
        if asset_id not in existing:
            manifest.add_asset(AssetRef(
                asset_id=asset_id, asset_type="image", data_ref="images",
                source="APS_MiniMaxH3Director",
                h3_labels=[f"Picture {index}"],
                note=f"connected picture reference {index}",
            ))


def _media_duration(value: Any) -> Optional[float]:
    """从 Comfy AUDIO/VIDEO 容器读取可用时长；未知则交由后端校验。"""
    if isinstance(value, dict):
        waveform = value.get("waveform")
        sample_rate = value.get("sample_rate")
        if waveform is not None and sample_rate:
            shape = getattr(waveform, "shape", ())
            if shape:
                return float(shape[-1]) / float(sample_rate)
    try:
        frames = value.get_frame_count()
        rate = value.get_frame_rate()
        if frames is not None and rate:
            return float(frames) / float(rate)
    except (AttributeError, TypeError, ValueError):
        pass
    return None

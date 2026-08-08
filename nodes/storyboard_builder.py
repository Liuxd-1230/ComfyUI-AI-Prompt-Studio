"""节点 5：Storyboard Builder —— 把故事拆成模型无关的结构化分镜。

经 LLM 把故事拆为 scene/shot/beat 层级（services/storyboard.py），
模型无关：禁止在此节点硬编码 ANIMA/H3 标签。
"""
from __future__ import annotations

import json

from ..schemas import types
from ..schemas.character import CharacterBible
from ..schemas.profile import AIProfile
from ..schemas.storyboard import ContinuityNote, SPLIT_MODES, Storyboard
from ..services.gateway import Gateway, GenerateRequest
from ..services.storyboard import (
    STORYBOARD_SCHEMA,
    build_continuity,
    build_storyboard_prompt,
    fallback_storyboard,
    parse_storyboard_json,
)
from ._helpers import require_api_key, resolve_profile_input


class APS_StoryboardBuilder:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "AI_PROFILE": (types.AI_PROFILE,),
            "story_text": ("STRING", {"default": "", "multiline": True,
                                      "tooltip": "故事/小说/对话/想法原文"}),
            "split_mode": (SPLIT_MODES, {"default": "auto",
                                         "tooltip": "scene=场景；shot=镜头；beat=节拍；auto=自动"}),
            "target_duration": ("FLOAT", {"default": 10.0, "min": 1.0, "max": 600.0,
                                          "tooltip": "目标视频时长（秒），供分镜节奏参考"}),
            "max_scenes": ("INT", {"default": 12, "min": 1, "max": 100,
                                   "tooltip": "最多场景数"}),
            "style": ("STRING", {"default": "", "multiline": False,
                                 "tooltip": "风格描述（如：Cinematic, live-action）"}),
        }, "optional": {
            "character_bible": (types.CHARACTER_BIBLE,),
            "character_book": (types.CHARACTER_BOOK,),
            "reference_manifest": (types.REFERENCE_MANIFEST,),
        }}

    RETURN_TYPES = (types.STORYBOARD, "STRING", "STRING")
    RETURN_NAMES = ("STORYBOARD", "story_summary", "continuity")
    FUNCTION = "build"
    CATEGORY = "AI Prompt Studio"
    DESCRIPTION = "把故事拆成模型无关的结构化分镜（保持人物/场景连续性，不写目标模型格式）。"

    def build(self, AI_PROFILE, story_text, split_mode, target_duration, max_scenes, style,
              character_bible=None, character_book=None, reference_manifest=None):
        profile = AIProfile.from_json(AI_PROFILE or {})
        if not profile.profile_id:
            raise ValueError("未收到 AI_PROFILE：请先连接 AI Model Profile 节点")
        if not story_text or not story_text.strip():
            raise ValueError("story_text 为空，请输入要拆分的故事文本")
        prof = resolve_profile_input(AI_PROFILE)
        api_key = require_api_key(prof)

        from ..schemas.character import CharacterBook
        from ..schemas.references import ReferenceManifest

        bible = CharacterBible.from_json(character_bible) if character_bible else None
        book = CharacterBook.from_json(character_book) if character_book else None
        if book is None and bible is not None:
            book = CharacterBook.from_bible(bible)
        manifest = ReferenceManifest.from_json(reference_manifest) if reference_manifest else None
        prompt = build_storyboard_prompt(story_text.strip(), split_mode,
                                         float(target_duration or 0),
                                         int(max_scenes or 12), style or "",
                                         bible, book, manifest)
        req = GenerateRequest(
            system="You are a professional storyboard artist. Output only JSON.",
            messages=[_msg(prompt)],
            web_search="off", reasoning="high", max_tokens=8192,
            timeout=prof.timeout,
            # 0.2.1 P1-17：原生 Structured Output（Provider 支持时）；否则提示词约束兜底
            output_schema=STORYBOARD_SCHEMA)
        result = Gateway().generate(prof, api_key, req)
        if result.has_error():
            raise ValueError(result.error.as_text)

        fallback_reason = ""
        try:
            sb = parse_storyboard_json(result.text, split_mode, style or "",
                                       float(target_duration or 0))
        except ValueError as exc:
            fallback_reason = str(exc)
            sb = fallback_storyboard(story_text, split_mode, style or "",
                                     float(target_duration or 0))
        if not sb.scenes:
            fallback_reason = "模型返回的 JSON 没有任何场景"
            sb = fallback_storyboard(story_text, split_mode, style or "",
                                     float(target_duration or 0))
        if len(sb.scenes) > int(max_scenes):
            raise ValueError(
                f"模型返回 {len(sb.scenes)} 个场景，超过 max_scenes={int(max_scenes)}；"
                "请重试或提高上限")
        shots = [shot for scene in sb.scenes for shot in scene.shots]
        if shots and target_duration:
            total = sum(max(0.0, shot.duration) for shot in shots)
            if total <= 0:
                each = float(target_duration) / len(shots)
                for shot in shots:
                    shot.duration = each
            else:
                scale = float(target_duration) / total
                for shot in shots:
                    shot.duration = round(max(0.01, shot.duration * scale), 3)
        sb.summary = story_text.strip()[:200]
        sb.continuity = build_continuity(sb)
        if fallback_reason:
            sb.continuity.append(ContinuityNote(
                note=("模型未遵守 Storyboard JSON 格式，已保留原故事并回退为一个"
                      f"可编辑镜头；未重复调用 API。原因：{fallback_reason}"),
                severity="warning"))

        continuity_text = json.dumps(
            [c.to_json() for c in sb.continuity], ensure_ascii=False)
        return (sb.to_json(), sb.summary, continuity_text)


def _msg(content: str):
    from ..schemas.results import ChatMessage

    return ChatMessage(role="user", content=content)

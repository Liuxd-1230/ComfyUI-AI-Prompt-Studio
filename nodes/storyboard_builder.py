"""节点 5：Storyboard Builder —— 把故事拆成模型无关的结构化分镜。

经 LLM 把故事拆为 scene/shot/beat 层级（services/storyboard.py），
模型无关：禁止在此节点硬编码 ANIMA/H3 标签。
"""
from __future__ import annotations

import json

from ..schemas import types
from ..schemas.character import CharacterBible
from ..schemas.profile import AIProfile
from ..schemas.storyboard import SPLIT_MODES, Storyboard
from ..services.gateway import Gateway, GenerateRequest
from ..services.storyboard import (
    build_continuity,
    build_storyboard_prompt,
    parse_storyboard_json,
)
from ._helpers import require_api_key, resolve_profile


class APS_StoryboardBuilder:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "AI_PROFILE": (types.AI_PROFILE,),
            "story_text": ("STRING", {"default": "", "multiline": True,
                                      "tooltip": "故事/小说/对话/想法原文"}),
            "split_mode": (SPLIT_MODES, {"default": "auto",
                                         "tooltip": "scene=场景；shot=镜头；beat=节拍；auto=自动"}),
            "target_duration": ("FLOAT", {"default": 10.0, "min": 0.0, "max": 600.0,
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
        prof = resolve_profile(profile.profile_id)
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
            timeout=prof.timeout)
        result = Gateway().generate(prof, api_key, req)
        if result.has_error():
            raise ValueError(result.error.as_text)

        sb = parse_storyboard_json(result.text, split_mode, style or "",
                                   float(target_duration or 0))
        if not sb.scenes:
            raise ValueError("模型没有返回任何场景，请调整 split_mode 或故事文本后重试")
        sb.summary = story_text.strip()[:200]
        sb.continuity = build_continuity(sb)

        continuity_text = json.dumps(
            [c.to_json() for c in sb.continuity], ensure_ascii=False)
        return (sb.to_json(), sb.summary, continuity_text)


def _msg(content: str):
    from ..schemas.results import ChatMessage

    return ChatMessage(role="user", content=content)

"""节点 5：Storyboard Builder —— 把故事拆成模型无关的结构化分镜。

Phase 1：注册与数据结构就绪；Phase 4 接入 LLM 后完整实现。
禁止在此节点硬编码 ANIMA/H3 标签。
"""

from ..schemas import types
from ..schemas.storyboard import SPLIT_MODES, Storyboard


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
            "reference_manifest": (types.REFERENCE_MANIFEST,),
        }}

    RETURN_TYPES = (types.STORYBOARD, "STRING", "STRING")
    RETURN_NAMES = ("STORYBOARD", "story_summary", "continuity")
    FUNCTION = "build"
    CATEGORY = "AI Prompt Studio"
    DESCRIPTION = "把故事拆成模型无关的结构化分镜（保持人物/场景连续性，不写目标模型格式）。"

    def build(self, AI_PROFILE, story_text, split_mode, target_duration, max_scenes, style,
              character_bible=None, reference_manifest=None):
        sb = Storyboard(split_mode=split_mode, style=style)
        sb.summary = story_text[:200] if story_text else ""
        # Phase 4 接入 LLM 完整拆分
        return (sb.to_json(), sb.summary, "[]")

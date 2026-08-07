"""节点 7：Model Prompt Composer —— 把自由文本/分镜/人物档案/参考转为目标图像模型提示词。

Phase 1：注册与数据结构就绪；Phase 4 实现 ANIMA/Generic/SDXL/FLUX/Custom Skill 渲染。
"""

from ..schemas import types
from ..schemas.prompt_plan import (
    ANIMA_VARIANTS,
    COMPOSER_OPERATIONS,
    PROMPT_MODES,
    GenerationProfile,
    PromptPlan,
    empty_validation,
)

TARGET_OPTIONS = [
    "anima_base", "anima_aesthetic", "anima_turbo",
    "generic_image", "sdxl", "flux_kontext", "custom_skill",
]


class APS_PromptComposer:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "AI_PROFILE": (types.AI_PROFILE,),
            "text": ("STRING", {"default": "", "multiline": True,
                                "tooltip": "自由文本/想法/需求描述"}),
            "target": (TARGET_OPTIONS, {"default": "anima_base",
                                        "tooltip": "目标图像模型"}),
            "operation": (COMPOSER_OPERATIONS, {"default": "generate",
                                                "tooltip": "generate=生成；expand=扩写；rewrite=改写；translate=翻译；audit=审计；repair=修复；convert=转换"}),
            "prompt_mode": (PROMPT_MODES, {"default": "hybrid",
                                           "tooltip": "tags=标签；natural_language=自然语言；hybrid=混合"}),
            "negative": ("STRING", {"default": "", "multiline": True,
                                    "tooltip": "自定义负面提示词种子；留空使用目标模型默认负面"}),
        }, "optional": {
            "story_item": (types.STORY_ITEM,),
            "character_bible": (types.CHARACTER_BIBLE,),
            "reference_manifest": (types.REFERENCE_MANIFEST,),
        }}

    RETURN_TYPES = ("STRING", "STRING", types.PROMPT_PLAN, types.GENERATION_PROFILE, "STRING")
    RETURN_NAMES = ("positive", "negative", "PROMPT_PLAN", "GENERATION_PROFILE", "validation")
    FUNCTION = "compose"
    CATEGORY = "AI Prompt Studio"
    DESCRIPTION = "把文本/分镜/人物档案/参考分析转换为目标图像模型提示词（ANIMA/Generic/SDXL/FLUX/自定义 Skill）。"

    def compose(self, AI_PROFILE, text, target, operation, prompt_mode, negative,
                story_item=None, character_bible=None, reference_manifest=None):
        family, variant = _split_target(target)
        plan = PromptPlan(target_family=family, target_variant=variant,
                          operation=operation, prompt_mode=prompt_mode)
        plan.warnings.append("Prompt Composer 功能将在 Phase 4 实现（ANIMA/Generic 渲染器）")
        profile = GenerationProfile(target_family=family, target_variant=variant)
        return (plan.positive, plan.negative, plan.to_json(), profile.to_json(),
                plan.validation.as_text())


def _split_target(target: str):
    if target.startswith("anima_"):
        return "anima", target[len("anima_"):]
    if target == "flux_kontext":
        return "flux", "kontext"
    if target == "generic_image":
        return "generic_image", ""
    if target == "sdxl":
        return "sdxl", ""
    return "custom_skill", ""

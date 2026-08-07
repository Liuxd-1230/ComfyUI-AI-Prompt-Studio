"""节点 7：Model Prompt Composer —— 把自由文本/分镜/人物档案/参考转为目标图像模型提示词。

目标家族：anima（Base/Aesthetic/Turbo，官方档案渲染）+ generic_image/sdxl/flux + custom_skill。
操作：generate/convert 确定性渲染；expand/rewrite/translate/repair 走 LLM Skill + 渲染后处理；
audit 只跑校验器。ANIMA 输出附带 ValidationReport（validators/anima.py）。
"""
from __future__ import annotations

import json

from ..renderers import render_anima, render_generic
from ..schemas import types
from ..schemas.character import CharacterBible
from ..schemas.profile import AIProfile
from ..schemas.prompt_plan import (
    ANIMA_VARIANTS,
    COMPOSER_OPERATIONS,
    PROMPT_MODES,
    GenerationProfile,
    PromptPlan,
)
from ..schemas.storyboard import StoryItem
from ..services.gateway import Gateway, GenerateRequest
from ..services.skills import get_skill
from ..validators.anima import validate_anima
from ._helpers import require_api_key, resolve_profile

TARGET_OPTIONS = [
    "anima_base", "anima_aesthetic", "anima_turbo",
    "generic_image", "sdxl", "flux_kontext", "custom_skill",
]

CONTENT_TIERS = ["safe", "sensitive"]
LLM_OPERATIONS = {"expand", "rewrite", "translate", "repair"}


class APS_PromptComposer:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "AI_PROFILE": (types.AI_PROFILE,),
            "text": ("STRING", {"default": "", "multiline": True,
                                "tooltip": "自由文本/想法/需求描述（story_item 连接时作为补充细节）"}),
            "target": (TARGET_OPTIONS, {"default": "anima_base",
                                        "tooltip": "目标图像模型"}),
            "operation": (COMPOSER_OPERATIONS, {"default": "generate",
                                                "tooltip": "generate=生成；expand=扩写；rewrite=改写；translate=翻译；audit=审计；repair=修复；convert=转换"}),
            "prompt_mode": (PROMPT_MODES, {"default": "hybrid",
                                           "tooltip": "tags=标签；natural_language=自然语言；hybrid=混合"}),
            "negative": ("STRING", {"default": "", "multiline": True,
                                    "tooltip": "自定义负面提示词种子；留空使用目标模型默认负面"}),
            "content_tier": (CONTENT_TIERS, {"default": "safe",
                                             "tooltip": "ANIMA safety 标签：safe / sensitive"}),
        }, "optional": {
            "story_item": (types.STORY_ITEM,),
            "character_bible": (types.CHARACTER_BIBLE,),
            "reference_manifest": (types.REFERENCE_MANIFEST,),
            "skill": ("STRING", {"default": "anima_expand", "multiline": False,
                                 "tooltip": "custom_skill / LLM 操作使用的 Skill id（内置：anima_expand/anima_rewrite/anima_repair/translate_en）"}),
            "lora_triggers": ("STRING", {"default": "", "multiline": False,
                                         "tooltip": "LoRA 触发词（逗号分隔），追加到提示词末尾"}),
        }}

    RETURN_TYPES = ("STRING", "STRING", types.PROMPT_PLAN, types.GENERATION_PROFILE, "STRING")
    RETURN_NAMES = ("positive", "negative", "PROMPT_PLAN", "GENERATION_PROFILE", "validation")
    FUNCTION = "compose"
    CATEGORY = "AI Prompt Studio"
    DESCRIPTION = "把文本/分镜/人物档案/参考分析转换为目标图像模型提示词（ANIMA/Generic/SDXL/FLUX/自定义 Skill）。"

    def compose(self, AI_PROFILE, text, target, operation, prompt_mode, negative,
                content_tier="safe", story_item=None, character_bible=None,
                reference_manifest=None, skill="anima_expand", lora_triggers=""):
        family, variant = _split_target(target)
        profile = AIProfile.from_json(AI_PROFILE or {})
        if not profile.profile_id:
            raise ValueError("未收到 AI_PROFILE：请先连接 AI Model Profile 节点")
        prof = resolve_profile(profile.profile_id)
        api_key = require_api_key(prof)

        bible = CharacterBible.from_json(character_bible) if character_bible else None
        base_text = _base_text(story_item, text)
        if not base_text.strip() and operation not in ("audit",):
            raise ValueError("text 与 story_item 均为空，请至少提供一个")

        lora = [t.strip() for t in lora_triggers.split(",") if t.strip()] if lora_triggers else []

        # -------- 按家族/操作分派
        if family == "anima":
            positive, neg, tags, warnings, gprofile = self._anima(
                prof, api_key, base_text, variant, operation, prompt_mode,
                negative, content_tier, bible, lora)
            validation = validate_anima(positive, neg, variant=variant,
                                        prompt_mode=prompt_mode)
        elif family == "custom_skill":
            positive, neg, tags, warnings, gprofile = self._skill_path(
                prof, api_key, base_text, operation, prompt_mode, negative,
                bible, skill, lora)
            validation = validate_anima(positive, neg, variant=variant,
                                        prompt_mode=prompt_mode)
        else:
            positive, neg, tags, warnings, gprofile = self._generic(
                prof, api_key, base_text, family, variant, operation,
                prompt_mode, negative, bible)
            validation = empty_report()

        plan = PromptPlan(target_family=family, target_variant=variant,
                          operation=operation, prompt_mode=prompt_mode,
                          positive=positive, negative=neg,
                          character_bindings=[_binding(bible)] if bible else [],
                          tags=tags, lora_triggers=lora,
                          warnings=warnings, validation=validation)
        return (positive, neg, plan.to_json(), gprofile.to_json(),
                validation.as_text())

    # ------------------------------------------------------------ ANIMA
    def _anima(self, prof, api_key, text, variant, operation, prompt_mode,
               negative, content_tier, bible, lora):
        if operation == "audit":
            # 审计：不修改输入，只校验
            from ..renderers.anima import (
                ANIMA_BASE_NEGATIVE,
                ANIMA_QUALITY_NEGATIVE,
                PROFILE_SETTINGS,
            )

            gprofile = GenerationProfile(target_family="anima", target_variant=variant,
                                         **PROFILE_SETTINGS[variant])
            neg = negative.strip() or (
                ANIMA_BASE_NEGATIVE if variant == "base" else ANIMA_QUALITY_NEGATIVE)
            return text.strip(), neg, [], [], gprofile
        if operation in LLM_OPERATIONS:
            skill_id = {"expand": "anima_expand", "rewrite": "anima_rewrite",
                        "translate": "translate_en", "repair": "anima_repair"}[operation]
            return self._llm_render(prof, api_key, skill_id, text, prompt_mode,
                                    negative, bible, lora, family="anima",
                                    variant=variant)
        # generate / convert：确定性渲染
        out = _as_dict(render_anima(text, variant=variant, prompt_mode=prompt_mode,
                                    content_tier=content_tier, bible=bible,
                                    negative_override=negative,
                                    lora_triggers=lora))
        return (out["positive"], out["negative"], out["tags"], out["warnings"],
                out["profile"])

    # ------------------------------------------------------------ 通用家族
    def _generic(self, prof, api_key, text, family, variant, operation,
                 prompt_mode, negative, bible):
        if operation in LLM_OPERATIONS:
            skill_id = {"expand": "anima_expand", "rewrite": "anima_rewrite",
                        "translate": "translate_en", "repair": "anima_repair"}[operation]
            out = self._llm_render(prof, api_key, skill_id, text, prompt_mode,
                                   negative, bible, [], family=family,
                                   variant=variant)
        else:
            out = render_generic(text, family=family, variant=variant,
                                 prompt_mode=prompt_mode, bible=bible,
                                 negative_override=negative)
        return (out["positive"], out["negative"], out.get("tags", []),
                out.get("warnings", []), out["profile"])

    # ------------------------------------------------------------ custom skill
    def _skill_path(self, prof, api_key, text, operation, prompt_mode,
                    negative, bible, skill, lora):
        if get_skill(skill) is None:
            raise ValueError(f"Skill 不存在: {skill!r}（内置：anima_expand/anima_rewrite/anima_repair/translate_en）")
        out = self._llm_render(prof, api_key, skill, text, prompt_mode,
                               negative, bible, lora, family="anima",
                               variant="base")
        return (out["positive"], out["negative"], out.get("tags", []),
                out.get("warnings", []), out["profile"])

    # ------------------------------------------------------------ LLM + 渲染
    def _llm_render(self, prof, api_key, skill_id, text, prompt_mode, negative,
                    bible, lora, family, variant):
        skill = get_skill(skill_id)
        req = GenerateRequest(system=skill.system_prompt,
                              messages=[_msg(text.strip())],
                              web_search="off", reasoning="medium",
                              max_tokens=4096, timeout=prof.timeout)
        result = Gateway().generate(prof, api_key, req)
        if result.has_error():
            raise ValueError(result.error.as_text)
        llm_out = result.text.strip()
        if skill.renderer == "anima":
            out = _as_dict(render_anima(llm_out, variant=variant,
                                        prompt_mode=prompt_mode, bible=bible,
                                        negative_override=negative,
                                        lora_triggers=lora))
        else:
            out = _as_dict(render_generic(llm_out, family=family, variant=variant,
                                          prompt_mode=prompt_mode, bible=bible,
                                          negative_override=negative))
        return (out["positive"], out["negative"], out["tags"], out["warnings"],
                out["profile"])


def _as_dict(result):
    return {"positive": result.positive, "negative": result.negative,
            "tags": result.tags, "warnings": result.warnings,
            "profile": result.profile}


def _binding(bible: CharacterBible) -> dict:
    return {"character": bible.name or bible.character_id,
            "attributes": bible.character_prompt()}


def _base_text(story_item, text) -> str:
    parts = []
    if story_item:
        item = StoryItem.from_json(story_item)
        if item.text:
            parts.append(item.text)
    if text and text.strip():
        parts.append(text.strip())
    return "\n".join(parts)


def _msg(content: str):
    from ..schemas.results import ChatMessage

    return ChatMessage(role="user", content=content)


def empty_report():
    from ..schemas.prompt_plan import empty_validation

    return empty_validation()


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

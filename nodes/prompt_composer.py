"""节点 7：Model Prompt Composer —— 把自由文本/分镜/人物档案/参考转为目标图像模型提示词。

目标家族：ANIMA + Z-Image Turbo + Qwen-Image-Edit-2511；旧 generic/SDXL/FLUX 保持兼容。
操作：generate/convert 确定性渲染；expand/rewrite/translate/repair 走 LLM Skill + 渲染后处理；
audit 只跑校验器。ANIMA 输出附带 ValidationReport（validators/anima.py）。

职责解耦（0.2.1）：只有真正要调用 LLM 的路径才 require_api_key
（expand/rewrite/translate/repair、ANIMA natural/hybrid generate、custom skill LLM）；
audit / convert / generate(tags) / ANIMA audit 完全离线。
content_tier（旧）迁移为 safety_tag（新，默认 none）：safety 标签只在用户显式选择时注入。
"""
from __future__ import annotations

import json

from ..renderers import render_anima, render_generic, render_special_image
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
from ._helpers import require_api_key, resolve_profile_input, try_api_key

TARGET_OPTIONS = [
    "anima_base", "anima_aesthetic", "anima_turbo",
    "z_image_turbo", "qwen_image_edit_2511",
    "generic_image", "custom_skill",
]

SAFETY_TAGS = ["none", "safe", "sensitive", "nsfw", "explicit"]

# 旧 content_tier → safety_tag 迁移（0.2.1 补充 P0）
CONTENT_TIER_MIGRATION = {"safe": "safe", "sensitive": "sensitive"}
LLM_OPERATIONS = {"expand", "rewrite", "translate", "repair"}


def _normalize_safety_tag(safety_tag: str) -> str:
    """归一化 safety_tag；旧值 content_tier（safe/sensitive）迁移；非法值回退 none。"""
    tag = (safety_tag or "").strip()
    if tag in CONTENT_TIER_MIGRATION:
        return CONTENT_TIER_MIGRATION[tag]
    return tag if tag in SAFETY_TAGS else "none"


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
            "prompt_mode": (PROMPT_MODES, {"default": "natural_language",
                                           "tooltip": "natural_language=自然语言（默认，官方推荐）；tags=官方标签结构；hybrid=少量控制标签+自然正文"}),
            "negative": ("STRING", {"default": "", "multiline": True,
                                    "tooltip": "自定义负面提示词种子；留空使用目标模型默认负面"}),
            "safety_tag": (SAFETY_TAGS, {"default": "none",
                                         "tooltip": "ANIMA safety 标签：none=不注入任何 Safety 标签（默认）；safe/sensitive/nsfw/explicit 按官方列表显式注入。Composer 只按用户选择渲染，不做内容审查"}),
        }, "optional": {
            "story_item": (types.STORY_ITEM,),
            "character_bible": (types.CHARACTER_BIBLE,),
            "character_book": (types.CHARACTER_BOOK,),
            "reference_manifest": (types.REFERENCE_MANIFEST,),
            "skill": ("STRING", {"default": "anima_expand", "multiline": False,
                                 "tooltip": "custom_skill / LLM 操作使用的 Skill id（内置：anima_expand/anima_rewrite/anima_repair/translate_en）"}),
            "lora_triggers": ("STRING", {"default": "", "multiline": False,
                                         "tooltip": "LoRA 触发词（逗号分隔），追加到提示词末尾"}),
            # 兼容旧工作流：content_tier 已并入 safety_tag（0.2.1 迁移，无独立语义）
            "content_tier": ("STRING", {"default": "", "multiline": False,
                                        "tooltip": "（已弃用）旧参数，由 safety_tag 取代；传入 safe/sensitive 时自动迁移"}),
        }}

    RETURN_TYPES = ("STRING", "STRING", types.PROMPT_PLAN, types.GENERATION_PROFILE, "STRING")
    RETURN_NAMES = ("positive", "negative", "PROMPT_PLAN", "GENERATION_PROFILE", "validation")
    FUNCTION = "compose"
    CATEGORY = "AI Prompt Studio"
    DESCRIPTION = "把文本/分镜/人物档案/图片引用转换为 ANIMA、Z-Image Turbo 或 Qwen-Image-Edit-2511 提示词。"

    def compose(self, AI_PROFILE, text, target, operation, prompt_mode, negative,
                safety_tag="none", story_item=None, character_bible=None,
                character_book=None, reference_manifest=None,
                skill="anima_expand", lora_triggers="", content_tier=""):
        family, variant = _split_target(target)
        profile = AIProfile.from_json(AI_PROFILE or {})
        if not profile.profile_id:
            raise ValueError("未收到 AI_PROFILE：请先连接 AI Model Profile 节点")
        prof = resolve_profile_input(AI_PROFILE)
        # 新工作流用 safety_tag；旧工作流传 content_tier 时迁移（兼容）。
        # 注意 safety_tag 默认 "none" 也是非空值，不能直接用 `or` 判断：
        # content_tier 非空 → 旧工作流 → 迁移优先；否则以 safety_tag 为准。
        if (content_tier or "").strip():
            safety_tag = content_tier
        safety_tag = _normalize_safety_tag(safety_tag)

        from ..schemas.character import CharacterBook

        book = CharacterBook.from_json(character_book) if character_book else None
        bible = CharacterBible.from_json(character_bible) if character_bible else None
        if bible is None and book is not None:
            bible = book.first_bible()  # 兼容：单人物工作流取容器内档案
        book_context = book.context_text() if book is not None else ""
        base_text = _base_text(story_item, text)
        if not base_text.strip() and operation not in ("audit",):
            raise ValueError("text 与 story_item 均为空，请至少提供一个")

        lora = [t.strip() for t in lora_triggers.split(",") if t.strip()] if lora_triggers else []

        # -------- 按家族/操作分派（audit 完全离线；LLM 路径才取密钥）
        if family == "anima":
            positive, neg, tags, warnings, gprofile = self._anima(
                prof, base_text, variant, operation, prompt_mode,
                negative, safety_tag, bible, lora, book_context)
            validation = validate_anima(positive, neg, variant=variant,
                                        prompt_mode=prompt_mode)
        elif family in {"z_image", "qwen_image_edit"}:
            positive, neg, tags, warnings, gprofile = self._special(
                prof, base_text, family, variant, operation, negative,
                reference_manifest)
            validation = _validate_special(positive, family, reference_manifest)
        elif family == "custom_skill":
            selected_skill = get_skill(skill)
            if selected_skill is None:
                raise ValueError(f"Skill 不存在或已停用: {skill!r}")
            if (selected_skill.renderer == "minimax_h3" or
                    selected_skill.target_family == "minimax_h3"):
                raise ValueError(
                    f"Skill {skill!r} 仅供 APS MiniMax H3 Director 使用，"
                    "不能由 Prompt Composer 渲染")
            family = selected_skill.target_family
            variant = selected_skill.target_variant
            positive, neg, tags, warnings, gprofile = self._skill_path(
                prof, base_text, operation, prompt_mode, negative,
                bible, skill, lora)
            wants_anima = family == "anima" or "anima" in selected_skill.validators
            wants_special = (family in {"z_image", "qwen_image_edit"} or
                             "special_image" in selected_skill.validators)
            validation = (_validate_special(positive, family, reference_manifest)
                          if wants_special else
                          validate_anima(positive, neg, variant=variant or "base",
                                         prompt_mode=prompt_mode)
                          if wants_anima else empty_report())
        else:
            positive, neg, tags, warnings, gprofile = self._generic(
                prof, base_text, family, variant, operation,
                prompt_mode, negative, bible, book, book_context)
            validation = empty_report()

        # 渲染器/Skill 的可执行性警告也必须出现在可见 validation 输出中，
        # 不能只藏在 PROMPT_PLAN JSON 里显示“通过且 0 warning”。
        for index, warning in enumerate(warnings):
            validation.add("warning", f"composer_warning_{index + 1}", warning)

        # 0.2.1b：character_bindings 记录全部人物（CharacterBook 场景不再只记 first_bible）
        if book is not None and book.characters:
            bindings = [_binding(b) for b in book.characters]
        elif bible is not None:
            bindings = [_binding(bible)]
        else:
            bindings = []

        plan = PromptPlan(target_family=family, target_variant=variant,
                          operation=operation, prompt_mode=prompt_mode,
                          positive=positive, negative=neg,
                          character_bindings=bindings,
                          tags=tags, lora_triggers=lora,
                          warnings=warnings, validation=validation)
        return (positive, neg, plan.to_json(), gprofile.to_json(),
                validation.as_text())

    # ------------------------------------------------------------ ANIMA
    def _anima(self, prof, text, variant, operation, prompt_mode,
               negative, safety_tag, bible, lora, book_context=""):
        if operation == "audit":
            # 审计：不修改输入，只校验；完全离线（0.2.1）
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
            repair_issues = ""
            if operation == "repair":
                # repair 把校验问题作为输入传给 LLM（只修列出的问题）
                from ..validators.anima import validate_anima

                repair_issues = validate_anima(
                    text, variant=variant, prompt_mode=prompt_mode).as_text()
            return self._llm_render(prof, skill_id, text, prompt_mode,
                                    negative, bible, lora, family="anima",
                                    variant=variant, safety_tag=safety_tag,
                                    repair_issues=repair_issues,
                                    book_context=book_context)
        if operation == "generate" and prompt_mode != "tags":
            # ANIMA 默认自然语言：LLM 转换用户意图（产品决策 D16）
            return self._llm_render(prof, "anima_expand", text, prompt_mode,
                                    negative, bible, lora, family="anima",
                                    variant=variant, safety_tag=safety_tag,
                                    book_context=book_context)
        # generate(tags) / convert：确定性渲染（完全离线）
        out = _as_dict(render_anima(text, variant=variant, prompt_mode=prompt_mode,
                                    safety_tag=safety_tag, bible=bible,
                                    negative_override=negative,
                                    lora_triggers=lora))
        return (out["positive"], out["negative"], out["tags"], out["warnings"],
                out["profile"])

    # ------------------------------------------------------------ 通用家族
    def _special(self, prof, text, family, variant, operation, negative,
                 reference_manifest=None):
        if operation in LLM_OPERATIONS or operation == "generate":
            skill_id = ("z_image_turbo_expand" if family == "z_image"
                        else "qwen_image_edit_2511")
            reference_context = _reference_context(reference_manifest)
            operation_context = {
                "generate": "[操作] 从用户意图生成目标模型提示词。",
                "expand": "[操作] 扩写可见细节，保持主体身份、数量与核心意图。",
                "rewrite": "[操作] 消除歧义和属性串位，不新增剧情。",
                "translate": "[操作] 仅翻译为清晰英文，禁止扩写或改变编辑动作。",
                "repair": "[操作] 只修复空内容、引用歧义、主体/位置不清等问题。",
            }[operation]
            return self._llm_render(
                prof, skill_id, text, "natural_language", negative,
                None, [], family=family, variant=variant,
                extra_context="\n".join(x for x in (operation_context, reference_context) if x))
        out = render_special_image(text, family=family, variant=variant,
                                   negative_override=negative)
        return (out["positive"], out["negative"], out["tags"],
                out["warnings"], out["profile"])

    # ------------------------------------------------------------ 通用家族（旧工作流兼容）
    def _generic(self, prof, text, family, variant, operation,
                 prompt_mode, negative, bible, book, book_context=""):
        if operation in LLM_OPERATIONS:
            skill_id = {"expand": "generic_expand", "rewrite": "generic_rewrite",
                        "translate": "translate_en", "repair": "generic_repair"}[operation]
            repair_issues = "检查并修复空提示词、歧义主体、相互矛盾或不可见的描述。" \
                if operation == "repair" else ""
            out = self._llm_render(prof, skill_id, text, prompt_mode,
                                   negative, bible, [], family=family,
                                   variant=variant, repair_issues=repair_issues,
                                   book_context=book_context, book=book)
        else:
            # 确定性渲染（完全离线）；CharacterBook 多人物信息由 render_generic 经 book 传入
            # （0.2.1a：全部人物进最终 prompt，不再只取第一个档案）
            out = render_generic(text, family=family, variant=variant,
                                 prompt_mode=prompt_mode, bible=bible, book=book,
                                 negative_override=negative)
        return (out["positive"], out["negative"], out.get("tags", []),
                out.get("warnings", []), out["profile"])

    # ------------------------------------------------------------ custom skill
    def _skill_path(self, prof, text, operation, prompt_mode,
                    negative, bible, skill, lora):
        selected = get_skill(skill)
        if selected is None:
            raise ValueError(f"Skill 不存在或已停用: {skill!r}")
        family = selected.target_family
        variant = selected.target_variant
        if operation in {"audit", "convert"}:
            if family == "anima":
                out = _as_dict(render_anima(
                    text, variant=variant or "base", prompt_mode=prompt_mode,
                    bible=bible, negative_override=negative, lora_triggers=lora))
            elif family in {"z_image", "qwen_image_edit"}:
                out = render_special_image(text, family=family, variant=variant,
                                           negative_override=negative)
            else:
                out = _as_dict(render_generic(
                    text, family=family, variant=variant, prompt_mode=prompt_mode,
                    bible=bible, negative_override=negative))
            return (out["positive"], out["negative"], out.get("tags", []),
                    out.get("warnings", []), out["profile"])
        out = self._llm_render(prof, skill, text, prompt_mode,
                               negative, bible, lora, family=family,
                               variant=variant)
        return (out["positive"], out["negative"], out.get("tags", []),
                out.get("warnings", []), out["profile"])

    # ------------------------------------------------------------ LLM + 渲染
    def _llm_render(self, prof, skill_id, text, prompt_mode, negative,
                    bible, lora, family, variant, safety_tag="none",
                    repair_issues="", book_context="", book=None,
                    extra_context=""):
        skill = get_skill(skill_id)
        api_key = require_api_key(prof)  # LLM 路径才要求 API Key（0.2.1）
        user = text.strip()
        if book_context and book_context.strip():
            user = f"[角色表]\n{book_context.strip()}\n[任务]\n{user}"
        if extra_context and extra_context.strip():
            user = f"{extra_context.strip()}\n[任务]\n{user}"
        if repair_issues and repair_issues.strip():
            user = f"[校验问题]\n{repair_issues.strip()}\n[待修复提示词]\n{user}"
        special_schema = ({"type": "object", "properties": {
            "positive": {"type": "string"}}, "required": ["positive"],
            "additionalProperties": False}
            if skill.renderer in {"z_image", "qwen_image_edit", "generic"} else None)
        req = GenerateRequest(system=skill.system_prompt,
                              messages=[_msg(user)],
                              web_search="off", reasoning="medium",
                              max_tokens=4096, timeout=prof.timeout,
                              json_mode=bool(special_schema), output_schema=special_schema)
        result = Gateway().generate(prof, api_key, req)
        if result.has_error():
            raise ValueError(result.error.as_text)
        llm_out = result.text.strip()
        if skill.renderer == "anima_plan":
            from ..renderers.anima import parse_anima_plan, render_anima_plan

            plan = parse_anima_plan(llm_out, bible)
            if family == "anima":
                out = _as_dict(render_anima_plan(
                    plan, variant=variant, prompt_mode=prompt_mode,
                    safety_tag=safety_tag, negative_override=negative,
                    lora_triggers=lora))
            else:
                body = plan.natural_body or llm_out
                out = render_generic(body, family=family, variant=variant,
                                     prompt_mode=prompt_mode, bible=bible, book=book,
                                     negative_override=negative)
        elif skill.renderer == "anima":
            out = _as_dict(render_anima(llm_out, variant=variant,
                                        prompt_mode=prompt_mode, bible=bible,
                                        negative_override=negative,
                                        lora_triggers=lora))
        elif skill.renderer in {"z_image", "qwen_image_edit"}:
            from ..services.reference import extract_json_object

            special_payload = extract_json_object(llm_out) or {}
            special_text = str(special_payload.get("positive", "")).strip()
            if not special_text:
                if not llm_out:
                    raise ValueError(f"Skill {skill.id} 返回了空内容")
                special_text = llm_out
            out = render_special_image(special_text, family=family, variant=variant,
                                       negative_override=negative)
            if not special_payload.get("positive"):
                out["warnings"].append(
                    f"Skill {skill.id} 未返回 positive JSON；已保留模型普通文本作为提示词")
        elif skill.renderer == "generic":
            from ..services.reference import extract_json_object

            payload = extract_json_object(llm_out) or {}
            body = str(payload.get("positive", "")).strip()
            if not body:
                if not llm_out:
                    raise ValueError(f"Skill {skill.id} 返回了空内容")
                body = llm_out
            out = _as_dict(render_generic(
                body, family=family, variant=variant, prompt_mode=prompt_mode,
                bible=bible, book=book, negative_override=negative))
            if not payload.get("positive"):
                out["warnings"].append(
                    f"Skill {skill.id} 未返回 positive JSON；已保留模型普通文本作为提示词")
        else:
            out = _as_dict(render_generic(llm_out, family=family, variant=variant,
                                          prompt_mode=prompt_mode, bible=bible, book=book,
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


def _validate_special(positive: str, family: str, reference_manifest=None):
    """专用模型的最低可执行契约；不再用空报告伪装“已审计”。"""
    report = empty_report()
    report.checks.extend(["non_empty", "reference_labels"])
    if not positive.strip():
        report.add("error", "empty_prompt", "提示词不能为空")
    if family == "qwen_image_edit":
        import re

        used = {int(n) for n in re.findall(r"\bFigure\s+(\d+)\b", positive)}
        if used and not reference_manifest:
            report.add("error", "missing_references", "使用了 Figure 引用但未连接参考清单")
        elif used:
            image_assets = [asset for asset in reference_manifest.assets
                            if asset.asset_type == "image"]
            available = set()
            for index, asset in enumerate(image_assets, start=1):
                labels = [asset.note, *getattr(asset, "h3_labels", [])]
                numbers = {int(n) for label in labels if label
                           for n in re.findall(r"\bFigure\s+(\d+)\b", label)}
                available.update(numbers or {index})
            for number in sorted(used - available):
                report.add("error", "missing_figure",
                           f"提示词引用 Figure {number}，但参考清单中没有这张图片")
    return report


def _split_target(target: str):
    if target.startswith("anima_"):
        return "anima", target[len("anima_"):]
    if target == "flux_kontext":
        return "flux", "kontext"
    if target == "z_image_turbo":
        return "z_image", "turbo"
    if target == "qwen_image_edit_2511":
        return "qwen_image_edit", "2511"
    if target == "generic_image":
        return "generic_image", ""
    if target == "sdxl":
        return "sdxl", ""
    return "custom_skill", ""


def _reference_context(reference_manifest) -> str:
    if not reference_manifest:
        return ""
    from ..schemas.references import ReferenceManifest

    manifest = ReferenceManifest.from_json(reference_manifest)
    if not manifest.assets:
        return ""
    lines = ["[已连接图片引用]"]
    for asset in manifest.assets:
        label = asset.note or asset.label_or_id()
        lines.append(f"{label}: asset_id={asset.asset_id}")
    return "\n".join(lines)

"""ANIMA 提示词渲染器（官方档案，docs/research.md §3）+ 结构化 Prompt Plan。

产品决策（docs/decisions.md D16）：
- 默认 prompt_mode = natural_language（ANIMA 以自然语言为核心）；
- LLM（经 Skill）产出结构化 AnimaPromptPlan，Python renderer 确定性组织；
- 三种 renderer 消费同一个 Plan：Natural（自然正文）/ Tags（官方标签结构）/
  Hybrid（少量控制标签块 + 自然正文，绝不把正文再当标签追加一遍）；
- Character Bible 通过 AnimaCharacter 绑定（required=锁定/稳定特征，
  variable=可变特征），身份特征自然融入正文，不机械 tag 化。

safety 标签（0.2.1 补充 P0）：
- safety_tag ∈ none/safe/sensitive/nsfw/explicit；默认 none = 不注入任何 Safety 标签；
- 仅当用户显式选择非 none 时，标签按官方排序插入 safety 段；
- Prompt Composer 只按用户选择渲染，不做内容审查 / 不自动修改等级。

三套档案：
- base：官方前缀 `masterpiece, best quality, score_7, ` + 官方负面（含 score_1..3）；
  （0.2.1 起 safe 不再固定注入，随 safety_tag 决定）
- aesthetic：官方明确建议正负都不用 score_*；保留人类式品质词；
- turbo：官方未给 score 指导 → 人类式品质词，无 score；CFG 1 / 8-12 步。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..schemas.character import CharacterBible
from ..schemas.anima import AnimaCharacter, AnimaPromptPlan
from ..schemas.prompt_plan import GenerationProfile

# ---------------------------------------------------------------- 官方档案
ANIMA_BASE_PREFIX = "masterpiece, best quality, score_7, "
ANIMA_BASE_NEGATIVE = ("worst quality, low quality, score_1, score_2, score_3, "
                       "artist name, blurry, jpeg artifacts, chromatic aberration")
ANIMA_QUALITY_NEGATIVE = ("worst quality, low quality, artist name, blurry, "
                          "jpeg artifacts, chromatic aberration")

# 官方 safety 标签全集（0.2.1 补充 P0：safe/sensitive/nsfw/explicit；none=不注入）
SAFETY_TAGS = {"safe", "sensitive", "nsfw", "explicit"}
SAFETY_TAG_RENDER = {"safe": "safe", "sensitive": "sensitive",
                     "nsfw": "nsfw", "explicit": "explicit"}
QUALITY_TAGS = {"masterpiece", "best quality", "good quality", "normal quality",
                "low quality", "worst quality"} | {f"score_{i}" for i in range(1, 10)}
META_TAGS = {"highres", "absurdres", "anime screenshot", "jpeg artifacts",
             "official art", "newest", "recent", "mid", "early", "old"}
COUNT_RE = re.compile(r"^\d+(girl|boy|other)s?$")
YEAR_RE = re.compile(r"^year \d{4}$")

PROFILE_SETTINGS = {
    "base": {"steps": 40, "cfg": 5.0, "sampler": "", "scheduler": ""},
    "aesthetic": {"steps": 40, "cfg": 4.5, "sampler": "", "scheduler": ""},
    "turbo": {"steps": 10, "cfg": 1.0, "sampler": "", "scheduler": ""},
}

PROMPT_MODES = ["natural_language", "tags", "hybrid"]


@dataclass
class AnimaRenderResult:
    positive: str = ""
    negative: str = ""
    tags: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    profile: GenerationProfile = field(default_factory=GenerationProfile)


# ---------------------------------------------------------------- 工具

def split_tags(text: str) -> List[str]:
    """按逗号切分并归一化（小写、去空白、去空、去重保序）。"""
    seen = []
    for raw in re.split(r"[,\n]+", text or ""):
        tag = raw.strip().lower()
        if tag and tag not in seen:
            seen.append(tag)
    return seen


def is_score_tag(tag: str) -> bool:
    return tag in QUALITY_TAGS and tag.startswith("score_")


def has_underscore_besides_score(tag: str) -> bool:
    return "_" in tag and not tag.startswith("score_")


def classify(tag: str) -> str:
    """按官方顺序分段：quality / meta_year / safety / count / artist / general。"""
    if tag in SAFETY_TAGS:
        return "safety"
    if tag in QUALITY_TAGS or (tag.startswith("score_") and tag in QUALITY_TAGS):
        return "quality"
    if tag in META_TAGS or YEAR_RE.match(tag) or tag in ("newest", "recent", "mid", "early", "old"):
        return "meta_year"
    if COUNT_RE.match(tag):
        return "count"
    if tag.startswith("@"):
        return "artist"
    return "general"


SEGMENT_ORDER = ["quality", "meta_year", "safety", "count", "artist", "general"]


def order_tags(tags: List[str]) -> List[str]:
    """按官方标签顺序排序（段内保持输入顺序）。"""
    buckets: Dict[str, List[str]] = {k: [] for k in SEGMENT_ORDER}
    for t in tags:
        buckets[classify(t)].append(t)
    out: List[str] = []
    for seg in SEGMENT_ORDER:
        out.extend(buckets[seg])
    return out


def _normalize_underscores(tags: List[str]) -> List[str]:
    """把非 score 标签里的下划线转空格（官方规范：只有 score_* 带下划线）。"""
    return [t.replace("_", " ") if has_underscore_besides_score(t) else t for t in tags]


def _dedupe(items: List[str]) -> List[str]:
    seen = []
    for t in items:
        t = t.strip()
        if t and t not in seen:
            seen.append(t)
    return seen


def _fragment_in(text: str, frag: str) -> bool:
    """frag 是否已作为（词边界的）片段出现在 text 中（大小写不敏感）。

    去重规则（0.2.1 P0-12）：以空白/标点作为词边界做子串匹配——
    "long black hair" 命中 "her long black hair"（避免机械追加），
    而 "hair" 不命中 "long black hair" 中的整体短语（避免过度删除）。
    """
    if not frag or not frag.strip():
        return False
    needle = frag.strip().lower()
    hay = (text or "").lower()
    start = 0
    while True:
        idx = hay.find(needle, start)
        if idx == -1:
            return False
        before = hay[idx - 1] if idx > 0 else " "
        after = hay[idx + len(needle):idx + len(needle) + 1] if idx + len(needle) < len(hay) else " "
        if (not before.isalnum()) and (not after.isalnum()):
            return True
        start = idx + 1


def validate_safety_tag(safety_tag: str) -> str:
    """归一化 safety_tag；none/safe/sensitive/nsfw/explicit；非法值回退 none（不注入）。"""
    tag = (safety_tag or "").strip()
    return tag if tag in SAFETY_TAG_RENDER else "none"


def _extract_json(raw: str) -> Optional[dict]:
    """容错提取 JSON 对象（去代码块围栏、截取首个 { ... }）。"""
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except ValueError:
                    return None
    return None


# ---------------------------------------------------------------- Plan 构建

def build_anima_plan(text: str, bible: Optional[CharacterBible] = None) -> AnimaPromptPlan:
    """确定性构建：输入文本为自然正文；Bible 锁定/稳定特征 → 人物绑定。"""
    plan = AnimaPromptPlan(scene_description=(text or "").strip())
    if bible is not None and (bible.character_prompt() or bible.name):
        c = AnimaCharacter(character_id=bible.character_id, name=bible.name or "")
        for t in bible.traits:
            v = (t.value or "").strip()
            if not v:
                continue
            if t.locked or t.category == "stable":
                c.required_traits.append(v)
            elif t.category in ("variable", "current"):
                c.variable_traits.append(v)
        if c.required_traits or c.variable_traits or c.name:
            plan.characters.append(c)
    return plan


def parse_anima_plan(raw: str, bible: Optional[CharacterBible] = None) -> AnimaPromptPlan:
    """把 LLM 输出的计划 JSON 容错解析为 AnimaPromptPlan。

    非 JSON 时回退：整段文本作为 scene_description，Bible 派生人物绑定（不伪造）。
    v1 的 natural_description/natural_body/character.description 只在 schema
    迁移边界消费，renderer 永远只接收 PNF v2。
    """
    data = _extract_json(raw)
    if data is not None:
        legacy_payload = dict(data)
        legacy_payload.setdefault("normal_form_version", "1.0")
        legacy_payload["natural_body"] = (
            _s(data.get("natural_description")) or _s(data.get("natural_body")))
        legacy_payload["control_tags"] = (
            _str_list(data.get("control_tags")) or _str_list(data.get("quality")))
        plan = AnimaPromptPlan.from_json(legacy_payload).normalized()
        if not plan.characters and bible is not None:
            plan.characters = build_anima_plan("", bible).characters
        if (not plan.scene_description and not plan.creative_notes and
                not plan.characters and
                not plan.control_tags and not plan.series_tags and
                not plan.artist_tags and not plan.supplemental_tags and
                not plan.environment and not plan.style and
                not plan.composition and not plan.lighting):
            # 空计划：兜底为原文
            plan.scene_description = (raw or "").strip()
        return plan
    plan = build_anima_plan(raw or "", bible)
    return plan


def _bible_characters(bible: Optional[CharacterBible]) -> List[AnimaCharacter]:
    return build_anima_plan("", bible).characters if bible is not None else []


# ---------------------------------------------------------------- 渲染

def render_anima(
    text: str,
    *,
    variant: str = "base",
    prompt_mode: str = "natural_language",
    safety_tag: str = "none",
    bible: Optional[CharacterBible] = None,
    negative_override: str = "",
    lora_triggers: Optional[List[str]] = None,
) -> AnimaRenderResult:
    """兼容入口：输入自由文本 → 确定性 Plan → 渲染。"""
    if prompt_mode == "tags":
        return _render_tags_from_text(text, variant=variant, safety_tag=safety_tag,
                                      bible=bible, negative_override=negative_override,
                                      lora_triggers=lora_triggers)
    plan = build_anima_plan(text, bible)
    return render_anima_plan(plan, variant=variant, prompt_mode=prompt_mode,
                             safety_tag=safety_tag,
                             negative_override=negative_override,
                             lora_triggers=lora_triggers)


def render_anima_plan(
    plan: AnimaPromptPlan,
    *,
    variant: str = "base",
    prompt_mode: str = "natural_language",
    safety_tag: str = "none",
    negative_override: str = "",
    lora_triggers: Optional[List[str]] = None,
) -> AnimaRenderResult:
    """统一渲染：Natural / Tags / Hybrid 消费同一个 Plan，绝不重复正文。

    safety_tag：none 不注入任何 Safety 标签；safe/sensitive/nsfw/explicit 按
    官方排序插入 safety 段（用户显式选择才注入，不做内容审查）。
    """
    if variant not in PROFILE_SETTINGS:
        raise ValueError(f"未知 ANIMA 变体 {variant!r}（可选：base/aesthetic/turbo）")
    if prompt_mode not in PROMPT_MODES:
        raise ValueError(f"未知 prompt_mode {prompt_mode!r}")

    result = AnimaRenderResult()
    result.profile = GenerationProfile(target_family="anima", target_variant=variant,
                                       **PROFILE_SETTINGS[variant])

    safety_tag = validate_safety_tag(safety_tag)
    safety = SAFETY_TAG_RENDER[safety_tag] if safety_tag in SAFETY_TAG_RENDER else ""
    if variant == "base":
        prefix = f"masterpiece, best quality, score_7, "
    else:
        prefix = f"masterpiece, best quality, "

    negative = (negative_override.strip() if negative_override and negative_override.strip()
                else (ANIMA_BASE_NEGATIVE if variant == "base" else ANIMA_QUALITY_NEGATIVE))
    constraints = [item.strip() for item in plan.negative_constraints if item.strip()]
    if constraints:
        negative = ", ".join(_dedupe(split_tags(negative) + constraints))
    lora = [t.strip() for t in (lora_triggers or []) if t and t.strip()]

    if prompt_mode == "natural_language":
        body = _natural_body(plan)
        positive = prefix + (f"{safety}, " if safety else "") + body
        positive = positive.rstrip(" ,")
    elif prompt_mode == "hybrid":
        control = _dedupe(_normalize_underscores(
            plan.control_tags + plan.series_tags + plan.artist_tags))
        # 用户显式选择的安全标签并入控制块；plan 建议的安全标签被忽略
        control = _dedupe(control + ([safety] if safety else []))
        body = _natural_body(plan)
        block = ", ".join(control)
        positive = prefix + (block + (", " if block and body else "") + body).rstrip(" ,")
        result.tags = control
    else:  # tags
        tags = _plan_tags(plan)
        merged = _dedupe(_normalize_underscores(tags)) + lora
        non_lora = merged[:len(merged) - len(lora)] if lora else merged
        if safety and safety not in non_lora:
            # 用户显式选择的安全标签按官方排序插入 safety 段（tags 正文含同标签则不重复）
            non_lora = _dedupe(order_tags([safety] + non_lora))
        ordered = order_tags(non_lora)
        if lora:
            ordered = ordered + lora
        positive = prefix + ", ".join(ordered)
        result.tags = ordered
        if any(has_underscore_besides_score(t) for t in tags):
            result.warnings.append(
                "检测到下划线标签（官方规范：标签间用空格，仅 score_* 允许下划线）——已自动转换")

    if lora:
        positive = positive.rstrip(" ,") + ", " + ", ".join(lora)

    result.positive = positive
    result.negative = negative

    if variant == "aesthetic" and any(t.startswith("score_") for t in plan.control_tags):
        result.warnings.append(
            "Aesthetic 官方建议不使用 score_* 标签（已按官方档案保留输入原样，可手动移除）")
    return result


# ---------------------------------------------------------------- 内部

def _natural_body(plan: AnimaPromptPlan) -> str:
    """自然正文：人物绑定 → 用户/LLM 正文 → 环境/光照/构图/风格。逐项与正文去重。"""
    parts: List[str] = []
    body = plan.scene_description or ""
    for c in plan.characters:
        desc = _assemble_character(c, body)
        if desc and not _fragment_in(body, desc):
            parts.append(desc)
    parts.extend(note.strip() for note in plan.creative_notes
                 if note.strip() and not _fragment_in(body, note))
    if body:
        parts.append(body)
    for env in plan.environment:
        e = (env or "").strip().rstrip(".")
        if e and not _fragment_in(body, e):
            parts.append(e + ".")
    if plan.lighting and plan.lighting.strip():
        parts.append(plan.lighting.strip().rstrip(".") + ".")
    if plan.composition and plan.composition.strip():
        parts.append(plan.composition.strip().rstrip(".") + ".")
    if plan.style:
        parts.append("The visual style is " + ", ".join(s.strip() for s in plan.style if s.strip()) + ".")
    return " ".join(p for p in parts if p).strip()


def _assemble_character(c: AnimaCharacter, body: str) -> str:
    """确定性组装人物块：身份特征与正文去重（词边界匹配），禁止属性串位。"""
    traits = [t for t in (c.required_traits + c.variable_traits)
              if t.strip() and not _fragment_in(body, t)]
    name = c.name.strip() or "A character"
    if traits:
        base = f"{name} with {', '.join(t.strip() for t in traits)}"
    else:
        base = name
    if c.action and c.action.strip():
        base += f", {c.action.strip()}"
    if c.position and c.position.strip():
        base = f"On the {c.position.strip()}, {base}"
    notes = [note.strip() for note in c.creative_notes
             if note.strip() and not _fragment_in(body, note)]
    if notes:
        base += ", " + ", ".join(notes)
    if base.strip() == name:
        return ""  # 没有任何新增信息，不输出孤立的角色名块
    return base


def _plan_tags(plan: AnimaPromptPlan) -> List[str]:
    """Derive tags from the same authoritative Plan used by natural rendering.

    0.2.1：plan.control_tags 里的 safety 标签（如 LLM Plan 建议 safe）不自动注入——
    safety 标签只由用户节点参数 safety_tag 决定（产品决策）。
    """
    tags = list(plan.control_tags + plan.series_tags + plan.artist_tags)
    for character in plan.characters:
        tags.extend([character.name, *character.required_traits,
                     *character.variable_traits, character.action,
                     character.position, *character.creative_notes])
    tags.extend(plan.environment)
    tags.extend(plan.style)
    tags.extend([plan.composition, plan.lighting])
    tags.extend(plan.creative_notes)
    tags.extend(plan.supplemental_tags)
    if plan.scene_description:
        tags.extend(split_tags(plan.scene_description))
    return [tag for tag in _dedupe(tags) if tag not in SAFETY_TAGS]


def _render_tags_from_text(text, *, variant, safety_tag, bible, negative_override,
                           lora_triggers) -> AnimaRenderResult:
    """旧 Tags 管线（显式 tags 模式）：Bible 补全 + 输入切标签 + 官方排序。"""
    result = AnimaRenderResult()
    result.profile = GenerationProfile(target_family="anima", target_variant=variant,
                                       **PROFILE_SETTINGS[variant])
    safety_tag = validate_safety_tag(safety_tag)
    safety = SAFETY_TAG_RENDER[safety_tag] if safety_tag in SAFETY_TAG_RENDER else ""
    if variant == "base":
        prefix = f"masterpiece, best quality, score_7, "
    else:
        prefix = f"masterpiece, best quality, "

    bible_tags: List[str] = []
    if bible is not None and bible.character_prompt():
        bible_tags = split_tags(bible.character_prompt())
    user_tags = split_tags(text)
    lora = [t.strip() for t in (lora_triggers or []) if t and t.strip()]
    pre_norm = bible_tags + user_tags
    merged = _normalize_underscores(bible_tags + user_tags) + lora

    seen: List[str] = []
    for t in merged:
        if t not in seen:
            seen.append(t)
    ordered = order_tags(seen[:len(seen) - len(lora)] if lora else seen)
    if lora:
        ordered = ordered + lora
    if safety and safety not in ordered:
        non_lora = ordered[:len(ordered) - len(lora)] if lora else ordered
        if safety not in non_lora:
            non_lora = _dedupe(order_tags([safety] + non_lora))
        ordered = order_tags(non_lora) + lora

    negative = (negative_override.strip() if negative_override and negative_override.strip()
                else (ANIMA_BASE_NEGATIVE if variant == "base" else ANIMA_QUALITY_NEGATIVE))

    result.positive = prefix + ", ".join(ordered)
    result.negative = negative
    result.tags = ordered
    if variant == "aesthetic" and any(t.startswith("score_") for t in ordered):
        result.warnings.append("Aesthetic 官方建议不使用 score_* 标签（已按官方档案保留输入原样，可手动移除）")
    if any(has_underscore_besides_score(t) for t in pre_norm):
        result.warnings.append("检测到下划线标签（官方规范：标签间用空格，仅 score_* 允许下划线）——已自动转换")
    return result


def _s(v: Any) -> str:
    return str(v).strip() if v else ""


def _str_list(v: Any) -> List[str]:
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list):
        return []
    out = []
    for x in v:
        s = str(x).strip()
        if s and s not in out:
            out.append(s)
    return out

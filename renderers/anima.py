"""ANIMA 提示词渲染器（官方档案，docs/research.md §3）+ 结构化 Prompt Plan。

产品决策（docs/decisions.md D16）：
- 默认 prompt_mode = natural_language（ANIMA 以自然语言为核心）；
- LLM（经 Skill）产出结构化 AnimaPromptPlan，Python renderer 确定性组织；
- 三种 renderer 消费同一个 Plan：Natural（自然正文）/ Tags（官方标签结构）/
  Hybrid（少量控制标签块 + 自然正文，绝不把正文再当标签追加一遍）；
- Character Bible 通过 AnimaCharacter 绑定（required=锁定/稳定特征，
  variable=可变特征），身份特征自然融入正文，不机械 tag 化。

三套档案：
- base：官方前缀 `masterpiece, best quality, score_7, safe, ` + 官方负面（含 score_1..3）；
- aesthetic：官方明确建议正负都不用 score_*；保留人类式品质词；
- turbo：官方未给 score 指导 → 人类式品质词，无 score；CFG 1 / 8-12 步。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..schemas.character import CharacterBible
from ..schemas.prompt_plan import GenerationProfile

# ---------------------------------------------------------------- 官方档案
ANIMA_BASE_PREFIX = "masterpiece, best quality, score_7, safe, "
ANIMA_BASE_NEGATIVE = ("worst quality, low quality, score_1, score_2, score_3, "
                       "artist name, blurry, jpeg artifacts, chromatic aberration")
ANIMA_QUALITY_NEGATIVE = ("worst quality, low quality, artist name, blurry, "
                          "jpeg artifacts, chromatic aberration")

QUALITY_TAGS = {"masterpiece", "best quality", "good quality", "normal quality",
                "low quality", "worst quality"} | {f"score_{i}" for i in range(1, 10)}
SAFETY_TAGS = {"safe", "sensitive", "nsfw", "explicit"}
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


# ---------------------------------------------------------------- 结构化 Plan

@dataclass
class AnimaCharacter:
    """一个人物绑定：身份特征（稳定/锁定）与可变特征分离，禁止属性串位。"""

    character_id: str = ""
    name: str = ""
    required_traits: List[str] = field(default_factory=list)   # 锁定/稳定身份
    variable_traits: List[str] = field(default_factory=list)   # 可变（服装/表情/姿态）
    action: str = ""
    position: str = ""               # left / right / center ...
    description: str = ""            # LLM 生成的完整主体描述（优先使用）


@dataclass
class AnimaPromptPlan:
    """ANIMA 中间计划：内容决策（LLM 或输入派生）与最终格式分离。

    natural_body / characters / environment / style / composition / lighting
    供 Natural 与 Hybrid 渲染；control/character/series/artist/visual 标签
    供 Tags 与 Hybrid 渲染（Hybrid 只用 control 级别的少量元数据标签）。
    """

    natural_body: str = ""
    characters: List[AnimaCharacter] = field(default_factory=list)
    control_tags: List[str] = field(default_factory=list)      # quality/safety/meta/count
    character_tags: List[str] = field(default_factory=list)
    series_tags: List[str] = field(default_factory=list)
    artist_tags: List[str] = field(default_factory=list)       # @artist
    visual_tags: List[str] = field(default_factory=list)
    style: List[str] = field(default_factory=list)
    environment: List[str] = field(default_factory=list)
    composition: str = ""
    lighting: str = ""
    negative_constraints: List[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return json.loads(json.dumps(self, default=lambda o: o.__dict__))


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


def _substr_in(text: str, frag: str) -> bool:
    """frag 是否已作为子串出现在 text（大小写不敏感）——用于正文去重。"""
    return bool(frag) and frag.strip().lower() in (text or "").lower()


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
    plan = AnimaPromptPlan(natural_body=(text or "").strip())
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

    非 JSON 时回退：整段文本作为 natural_body，Bible 派生人物绑定（不伪造）。
    """
    data = _extract_json(raw)
    if data is not None:
        plan = AnimaPromptPlan()
        plan.natural_body = _s(data.get("natural_description")) or _s(data.get("natural_body"))
        plan.control_tags = _str_list(data.get("control_tags")) or _str_list(data.get("quality"))
        plan.character_tags = _str_list(data.get("character_tags"))
        plan.series_tags = _str_list(data.get("series_tags"))
        plan.artist_tags = _str_list(data.get("artist_tags"))
        plan.visual_tags = _str_list(data.get("visual_tags"))
        plan.style = _str_list(data.get("style"))
        plan.environment = _str_list(data.get("environment"))
        plan.composition = _s(data.get("composition"))
        plan.lighting = _s(data.get("lighting"))
        plan.negative_constraints = _str_list(data.get("negative_constraints"))
        for c in data.get("characters") or []:
            if not isinstance(c, dict):
                continue
            plan.characters.append(AnimaCharacter(
                character_id=_s(c.get("character_id")),
                name=_s(c.get("name")),
                required_traits=_str_list(c.get("required_traits")),
                variable_traits=_str_list(c.get("variable_traits")),
                action=_s(c.get("action")),
                position=_s(c.get("position")),
                description=_s(c.get("description"))))
        if not plan.characters and bible is not None:
            plan.characters = build_anima_plan("", bible).characters
        if not plan.natural_body and not plan.characters and not plan.control_tags:
            # 空计划：兜底为原文
            plan.natural_body = (raw or "").strip()
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
    content_tier: str = "safe",
    bible: Optional[CharacterBible] = None,
    negative_override: str = "",
    lora_triggers: Optional[List[str]] = None,
) -> AnimaRenderResult:
    """兼容入口：输入自由文本 → 确定性 Plan → 渲染。"""
    if prompt_mode == "tags":
        return _render_tags_from_text(text, variant=variant, content_tier=content_tier,
                                      bible=bible, negative_override=negative_override,
                                      lora_triggers=lora_triggers)
    plan = build_anima_plan(text, bible)
    return render_anima_plan(plan, variant=variant, prompt_mode=prompt_mode,
                             content_tier=content_tier,
                             negative_override=negative_override,
                             lora_triggers=lora_triggers)


def render_anima_plan(
    plan: AnimaPromptPlan,
    *,
    variant: str = "base",
    prompt_mode: str = "natural_language",
    content_tier: str = "safe",
    negative_override: str = "",
    lora_triggers: Optional[List[str]] = None,
) -> AnimaRenderResult:
    """统一渲染：Natural / Tags / Hybrid 消费同一个 Plan，绝不重复正文。"""
    if variant not in PROFILE_SETTINGS:
        raise ValueError(f"未知 ANIMA 变体 {variant!r}（可选：base/aesthetic/turbo）")
    if prompt_mode not in PROMPT_MODES:
        raise ValueError(f"未知 prompt_mode {prompt_mode!r}")

    result = AnimaRenderResult()
    result.profile = GenerationProfile(target_family="anima", target_variant=variant,
                                       **PROFILE_SETTINGS[variant])

    tier = content_tier if content_tier in ("safe", "sensitive") else "safe"
    if variant == "base":
        prefix = f"masterpiece, best quality, score_7, {tier}, "
    else:
        prefix = f"masterpiece, best quality, {tier}, "

    negative = (negative_override.strip() if negative_override and negative_override.strip()
                else (ANIMA_BASE_NEGATIVE if variant == "base" else ANIMA_QUALITY_NEGATIVE))
    lora = [t.strip() for t in (lora_triggers or []) if t and t.strip()]

    if prompt_mode == "natural_language":
        body = _natural_body(plan)
        positive = (prefix + body).rstrip(" ,")
    elif prompt_mode == "hybrid":
        control = _dedupe(_normalize_underscores(
            plan.control_tags + plan.series_tags + plan.artist_tags))
        body = _natural_body(plan)
        block = ", ".join(control)
        positive = prefix + (block + (", " if block and body else "") + body).rstrip(" ,")
        result.tags = control
    else:  # tags
        tags = _plan_tags(plan)
        merged = _dedupe(_normalize_underscores(tags)) + lora
        ordered = order_tags(merged[:len(merged) - len(lora)] if lora else merged)
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
    if content_tier not in ("safe", "sensitive"):
        result.warnings.append(f"content_tier={content_tier!r} 未知，回退 safe")
    return result


# ---------------------------------------------------------------- 内部

def _natural_body(plan: AnimaPromptPlan) -> str:
    """自然正文：人物绑定 → 用户/LLM 正文 → 环境/光照/构图/风格。逐项与正文去重。"""
    parts: List[str] = []
    body = plan.natural_body or ""
    for c in plan.characters:
        desc = c.description.strip() if c.description and c.description.strip() else _assemble_character(c, body)
        if desc and not _substr_in(body, desc):
            parts.append(desc)
    if body:
        parts.append(body)
    for env in plan.environment:
        e = (env or "").strip().rstrip(".")
        if e and not _substr_in(body, e):
            parts.append(e + ".")
    if plan.lighting and plan.lighting.strip():
        parts.append(plan.lighting.strip().rstrip(".") + ".")
    if plan.composition and plan.composition.strip():
        parts.append(plan.composition.strip().rstrip(".") + ".")
    if plan.style:
        parts.append("The visual style is " + ", ".join(s.strip() for s in plan.style if s.strip()) + ".")
    return " ".join(p for p in parts if p).strip()


def _assemble_character(c: AnimaCharacter, body: str) -> str:
    """确定性组装人物块：身份特征与正文去重，禁止属性串位。"""
    traits = [t for t in (c.required_traits + c.variable_traits)
              if t.strip() and not _substr_in(body, t)]
    name = c.name.strip() or "A character"
    if traits:
        base = f"{name} with {', '.join(t.strip() for t in traits)}"
    else:
        base = name
    if c.action and c.action.strip():
        base += f", {c.action.strip()}"
    if c.position and c.position.strip():
        base = f"On the {c.position.strip()}, {base}"
    if base.strip() == name:
        return ""  # 没有任何新增信息，不输出孤立的角色名块
    return base


def _plan_tags(plan: AnimaPromptPlan) -> List[str]:
    """Tags 模式标签源：显式标签字段；为空时按 tags 语义把正文切为标签。"""
    explicit = _dedupe(plan.control_tags + plan.character_tags + plan.series_tags
                       + plan.artist_tags + plan.visual_tags)
    if explicit:
        return explicit
    if plan.natural_body:
        return split_tags(plan.natural_body)
    return []


def _render_tags_from_text(text, *, variant, content_tier, bible, negative_override,
                           lora_triggers) -> AnimaRenderResult:
    """旧 Tags 管线（显式 tags 模式）：Bible 补全 + 输入切标签 + 官方排序。"""
    result = AnimaRenderResult()
    result.profile = GenerationProfile(target_family="anima", target_variant=variant,
                                       **PROFILE_SETTINGS[variant])
    tier = content_tier if content_tier in ("safe", "sensitive") else "safe"
    if variant == "base":
        prefix = f"masterpiece, best quality, score_7, {tier}, "
    else:
        prefix = f"masterpiece, best quality, {tier}, "

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

    negative = (negative_override.strip() if negative_override and negative_override.strip()
                else (ANIMA_BASE_NEGATIVE if variant == "base" else ANIMA_QUALITY_NEGATIVE))

    result.positive = prefix + ", ".join(ordered)
    result.negative = negative
    result.tags = ordered
    if variant == "aesthetic" and any(t.startswith("score_") for t in ordered):
        result.warnings.append("Aesthetic 官方建议不使用 score_* 标签（已按官方档案保留输入原样，可手动移除）")
    if any(has_underscore_besides_score(t) for t in pre_norm):
        result.warnings.append("检测到下划线标签（官方规范：标签间用空格，仅 score_* 允许下划线）——已自动转换")
    if content_tier not in ("safe", "sensitive"):
        result.warnings.append(f"content_tier={content_tier!r} 未知，回退 safe")
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

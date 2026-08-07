"""ANIMA 提示词校验器（rules：官方档案 + 规范要求）。

规则：
- base 变体必须带官方前缀（masterpiece, best quality, score_7）；
- aesthetic/turbo 正负提示词不得含 score_* 标签（官方明确）；
- 标签小写；除 score_* 外不允许下划线；不允许重复标签；
- 负面提示词必须含核心项（worst quality / low quality / blurry 等）；
- natural_language 模式跳过标签级检查。
- safety 标签（0.2.1）：最多一个；必须位于官方 safety 段；
  nsfw/explicit 不是语法错误（校验器只查格式，不做内容审查）。
"""
from __future__ import annotations

import re
from typing import List

from ..renderers.anima import (
    ANIMA_BASE_NEGATIVE,
    ANIMA_BASE_PREFIX,
    SAFETY_TAGS,
    has_underscore_besides_score,
)
from ..schemas.prompt_plan import ValidationReport

CORE_NEGATIVE = ["worst quality", "low quality", "blurry"]


def _raw_tokens(text: str) -> List[str]:
    """按逗号/换行切分，保留原始大小写（供大写/重复检查）。"""
    return [t.strip() for t in re.split(r"[,\n]+", text or "") if t.strip()]


def _segment_of(tag: str) -> str:
    """官方标签分段（与 renderer 的 classify 保持一致）。"""
    if tag in SAFETY_TAGS:
        return "safety"
    from ..renderers.anima import classify

    return classify(tag)


def validate_anima(positive: str, negative: str = "",
                   *, variant: str = "base",
                   prompt_mode: str = "tags") -> ValidationReport:
    report = ValidationReport()
    report.checks.append(f"anima_{variant}")

    if not positive or not positive.strip():
        report.add("error", "anima_empty_positive", "正提示词为空")
        return report

    if prompt_mode == "natural_language":
        # 自然语言模式：官方允许任意混排，跳过标签级规则
        if variant == "base" and "masterpiece" not in positive[:60]:
            report.add("warning", "anima_nl_prefix", "自然语言模式建议 quality 词放句首")
        return report

    raw = _raw_tokens(positive)
    tags = [t.lower() for t in raw]
    neg_raw = _raw_tokens(negative)
    neg_tags = [t.lower() for t in neg_raw]

    # 前缀（base）
    if variant == "base":
        head = ", ".join(raw[:3]).lower()
        if "masterpiece" not in head or "best quality" not in head:
            report.add("warning", "anima_prefix",
                       "Base 官方前缀建议以 `masterpiece, best quality, score_7, ` 开头")
        if "score_7" not in tags:
            report.add("warning", "anima_score7", "Base 推荐 score_7 品质标签")

    # score 约束
    if variant in ("aesthetic", "turbo"):
        for t in tags:
            if t.startswith("score_"):
                report.add("warning", "anima_no_score",
                           f"{variant} 官方建议不使用 score_* 标签（发现 {t!r}）")
        for t in neg_tags:
            if t.startswith("score_"):
                report.add("warning", "anima_no_score_neg",
                           f"{variant} 负面提示词建议移除 score_* 标签（发现 {t!r}）")

    # safety 标签：最多一个；必须位于 safety 段；nsfw/explicit 不是语法错误
    safety_in = [t for t in tags if t in SAFETY_TAGS]
    if len(safety_in) > 1:
        report.add("warning", "anima_safety_multiple",
                   f"检测到多个 safety 标签 {safety_in!r}，官方排序中同一时刻只应有一个")
    for t in safety_in:
        if _segment_of(t) != "safety":
            report.add("warning", "anima_safety_position",
                       f"safety 标签 {t!r} 未位于官方 safety 段（quality → meta_year → safety → ...）")

    # 下划线（仅 score_* 允许）与重复——用原始 token（split 前）
    seen = set()
    for tok in raw:
        low = tok.lower()
        if has_underscore_besides_score(low):
            report.add("warning", "anima_underscore",
                       f"标签 {tok!r} 含下划线（官方：标签间用空格，仅 score_* 允许下划线）")
        if re.search(r"[A-Z]", tok):
            report.add("warning", "anima_uppercase", f"标签 {tok!r} 含大写（官方要求小写标签）")
        if low in seen:
            report.add("warning", "anima_duplicate", f"重复标签 {tok!r}")
        seen.add(low)

    # 负面核心项
    for core in CORE_NEGATIVE:
        if core not in neg_tags:
            report.add("warning", "anima_negative_core",
                       f"负面提示词缺少核心项 {core!r}")
    return report

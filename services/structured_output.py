"""模型原始输出的有界摘录（诊断文本进日志/错误信息前必须先限长）。"""
from __future__ import annotations


RAW_EXCERPT_LIMIT = 500


def raw_excerpt(raw: object) -> str:
    value = str(raw or "").strip()
    if len(value) <= RAW_EXCERPT_LIMIT:
        return value
    return value[:RAW_EXCERPT_LIMIT] + "…"

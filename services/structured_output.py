"""Bounded diagnostics for provider structured-output protocol failures."""
from __future__ import annotations

import logging
from collections.abc import Iterable


RAW_EXCERPT_LIMIT = 500
ISSUE_LIMIT = 8


def bounded_issues(issues: Iterable[object]) -> list[str]:
    """Deduplicate validation messages and cap user-facing error volume."""
    unique: list[str] = []
    for issue in issues:
        clean = " ".join(str(issue).split())
        if clean and clean not in unique:
            unique.append(clean)
        if len(unique) >= ISSUE_LIMIT:
            break
    return unique


def raw_excerpt(raw: object) -> str:
    value = str(raw or "").strip()
    if len(value) <= RAW_EXCERPT_LIMIT:
        return value
    return value[:RAW_EXCERPT_LIMIT] + "…"


def log_protocol_failure(logger: logging.Logger, label: str, raw: object,
                         issues: Iterable[object] = ()) -> None:
    logger.warning(
        "%s structured output rejected; issues=%s; raw=%s",
        label, bounded_issues(issues), raw_excerpt(raw))


def protocol_failure_message(label: str, raw: object,
                             issues: Iterable[object] = ()) -> str:
    details = bounded_issues(issues)
    issue_text = "；".join(details) if details else "无法解析 JSON 对象"
    return (f"{label} 在一次重试后仍未返回合法结构化结果：{issue_text}。"
            f"上一版保持不变。模型原始输出（截断）：{raw_excerpt(raw)}")

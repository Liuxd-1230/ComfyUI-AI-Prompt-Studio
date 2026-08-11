"""Shared rendering of deterministic semantic issues for nodes and logs."""
from __future__ import annotations

from typing import Any

from ..schemas.semantic import SemanticIssue


def unique_semantic_issues(issues: list[SemanticIssue]) -> list[SemanticIssue]:
    result: list[SemanticIssue] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for issue in issues:
        key = (issue.severity, issue.code, issue.path,
               issue.message, issue.reason)
        if key not in seen:
            seen.add(key)
            result.append(issue)
    return result


def append_semantic_issues(report: Any,
                           issues: list[SemanticIssue]) -> None:
    for issue in unique_semantic_issues(issues):
        detail = f"{issue.message}（路径: {issue.path}；原因: {issue.reason}）"
        report.add(issue.severity, issue.code, detail, issue.path)


def semantic_error_text(issues: list[SemanticIssue]) -> str:
    return "\n".join(
        f"[{issue.code}] {issue.path}: {issue.message}；{issue.reason}"
        for issue in unique_semantic_issues(issues)
        if issue.severity == "error")

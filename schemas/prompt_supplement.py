"""Persistent metadata for user-authored Markdown prompt supplements."""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import Any

from .base import Schema

MAX_PROMPT_SUPPLEMENT_BYTES = 256 * 1024


@dataclasses.dataclass
class PromptSupplement(Schema):
    """A local Markdown document with explicit applicability metadata."""

    CURRENT_SCHEMA_VERSION = "1.0"

    supplement_id: str = ""
    title: str = ""
    filename: str = ""
    path: str = ""
    content_hash: str = ""
    enabled: bool = True
    source: str = "user"
    scope: str = "target"
    target_families: list[str] = dataclasses.field(default_factory=list)
    node_ids: list[str] = dataclasses.field(default_factory=list)
    description: str = ""
    size: int = 0
    created_at: str = ""
    updated_at: str = ""

    def validate(self) -> list[str]:
        issues: list[str] = []
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", self.supplement_id):
            issues.append("supplement_id 只能包含字母、数字、下划线和连字符，长度不超过 64")
        if not self.title.strip():
            issues.append("title 不能为空")
        if len(self.title) > 160:
            issues.append("title 长度不能超过 160")
        if (not self.filename.strip() or Path(self.filename).name != self.filename
                or Path(self.filename).suffix.lower() != ".md"):
            issues.append("filename 必须是无目录的 .md 文件名")
        if self.content_hash and not re.fullmatch(r"[0-9a-f]{64}", self.content_hash):
            issues.append("content_hash 必须是 SHA-256 十六进制摘要")
        if self.source not in {"user", "project", "curated_official_note"}:
            issues.append("source 必须是 user、project 或 curated_official_note")
        if self.scope not in {"global", "node", "target"}:
            issues.append("scope 必须是 global、node 或 target")
        if self.size < 0 or self.size > MAX_PROMPT_SUPPLEMENT_BYTES:
            issues.append("size 必须在 0 到 256 KiB 之间")
        if self.scope == "node" and not self.node_ids:
            issues.append("node 范围必须至少指定一个 node_id")
        if self.scope == "target" and any(not item for item in self.target_families):
            issues.append("target_families 不能包含空值")
        return issues

    @classmethod
    def from_json(cls, data: Any) -> "PromptSupplement":
        result = super().from_json(data)
        if not isinstance(result, cls):
            raise TypeError("PromptSupplement 反序列化类型错误")
        return result

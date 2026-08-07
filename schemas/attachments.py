"""附件结构：Attachment / AttachmentList（API 附件，产品决策 D20）。

类型：text（文本内容，直接进上下文/消息）、image（图片，走视觉部分）、
file（任意文件，走 input_file/file 内容部分，无能力时本地提取文本降级）。
安全约束（§32）：
- 内容不写日志；
- 文件路径必须解析在受控目录内（禁止绝对路径穿越 / .. / 符号链接逃逸）；
- 大小上限（size_bytes 强制校验）；
- 临时文件随请求清理。
"""
from __future__ import annotations

import base64
import dataclasses
import mimetypes
from dataclasses import dataclass, field
from typing import List

from .base import Schema

# 附件类型
ATTACHMENT_KINDS = ["text", "image", "file"]

# 安全上限（默认；可被调用方收紧）
MAX_TEXT_BYTES = 512 * 1024          # 文本附件 512 KB
MAX_IMAGE_BYTES = 20 * 1024 * 1024   # 图片附件 20 MB（data URI 会再膨胀 ~1.33x）
MAX_FILE_BYTES = 20 * 1024 * 1024    # 普通文件 20 MB

_IMAGE_MIME_PREFIX = ("image/",)


@dataclasses.dataclass
class Attachment(Schema):
    attachment_id: str = ""
    kind: str = "text"               # text | image | file
    name: str = ""                   # 显示名 / 文件名（不做路径使用）
    mime_type: str = ""
    content: str = ""                # text=原文；image/file=data URI 或 base64 载荷
    is_data_uri: bool = False
    size_bytes: int = 0
    source: str = ""                 # 来源标记（如 "widget:path"、"list:json"）
    problems: List[str] = field(default_factory=list)

    def __post_init__(self):
        if self.kind not in ATTACHMENT_KINDS:
            self.problems.append(f"非法附件类型 {self.kind!r}")
        if self.size_bytes < 0:
            self.problems.append("size_bytes 不能为负")
        # 文件名只作为展示名，禁止把路径语义带入（防穿越）
        self.name = (self.name or "").replace("\\", "/").split("/")[-1]

    def validate(self) -> List[str]:
        problems = list(self.problems)
        if self.kind == "text" and self.size_bytes > MAX_TEXT_BYTES:
            problems.append(f"文本附件超过大小上限（{MAX_TEXT_BYTES} 字节）")
        if self.kind == "image" and self.size_bytes > MAX_IMAGE_BYTES:
            problems.append(f"图片附件超过大小上限（{MAX_IMAGE_BYTES} 字节）")
        if self.kind == "file" and self.size_bytes > MAX_FILE_BYTES:
            problems.append(f"文件附件超过大小上限（{MAX_FILE_BYTES} 字节）")
        return problems

    @classmethod
    def from_text(cls, text: str, name: str = "") -> "Attachment":
        data = (text or "").encode("utf-8")
        return cls(kind="text", name=name or "text.txt",
                   mime_type="text/plain", content=text or "",
                   size_bytes=len(data), source="inline")

    @classmethod
    def from_data_uri(cls, data_uri: str, name: str = "", mime_type: str = "") -> "Attachment":
        """从 data URI 构造图片/文件附件。data_uri 形如 data:<mime>;base64,<payload>。"""
        mime = mime_type
        payload = data_uri
        if data_uri.startswith("data:"):
            head, _, payload = data_uri.partition(",")
            if not mime and ";" in head:
                mime = head[5:].split(";", 1)[0]
        try:
            size = len(base64.b64decode(payload, validate=True))
        except Exception:  # noqa: BLE001 - 非法 base64
            size = 0
        kind = "image" if mime.startswith(_IMAGE_MIME_PREFIX) else "file"
        return cls(kind=kind, name=name or "attachment.bin", mime_type=mime or "application/octet-stream",
                   content=data_uri, is_data_uri=True, size_bytes=size, source="data_uri")

    @classmethod
    def from_base64(cls, b64: str, name: str = "", mime_type: str = "") -> "Attachment":
        mime = mime_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
        kind = "image" if mime.startswith(_IMAGE_MIME_PREFIX) else "file"
        try:
            size = len(base64.b64decode(b64, validate=True))
        except Exception:  # noqa: BLE001
            size = 0
        uri = f"data:{mime};base64,{b64}"
        return cls(kind=kind, name=name or "attachment.bin", mime_type=mime,
                   content=uri, is_data_uri=True, size_bytes=size, source="base64")

    def as_data_uri(self) -> str:
        return self.content if self.is_data_uri else f"data:{self.mime_type};base64,{self.content}"


@dataclasses.dataclass
class AttachmentList(Schema):
    """附件容器（ATTACHMENT_LIST）。"""

    attachments: List[Attachment] = field(default_factory=list)

    def validate(self) -> List[str]:
        problems: List[str] = []
        for a in self.attachments:
            problems.extend(a.validate())
        return problems

    def by_kind(self, kind: str) -> List[Attachment]:
        return [a for a in self.attachments if a.kind == kind]

    def summary(self) -> str:
        return "; ".join(
            f"{a.kind}:{a.name}({a.size_bytes}B)" for a in self.attachments) or "（无附件）"

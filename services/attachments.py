"""附件服务：本地路径安全解析 + 能力门槛（视觉/文件）与降级规则。

安全（§32）：路径必须解析在受控输入目录内（拒绝 .. 逃逸 / 绝对路径绕过）；
内容不写日志；大小上限；附件生命周期短（文本/图片直接内联，无临时文件遗留）。
降级规则（产品决策 D20）：
- 文本附件：任何协议直接作为文本内容发送，无需能力；
- 图片附件：主模型必须支持视觉（caps.vision 或档案 supports_vision），否则**报错**，
  绝不静默丢弃伪装成功；
- 文件附件：支持文件发送（caps.files 或档案 supports_files）→ 发送文件内容部分；
  否则本地提取文本成功 → 文本降级 + warning；提取失败 → 报错。
"""
from __future__ import annotations

import base64
import mimetypes
import os
from pathlib import Path
from typing import List, Optional, Tuple

from ..schemas.attachments import (
    MAX_FILE_BYTES,
    MAX_IMAGE_BYTES,
    MAX_TEXT_BYTES,
    Attachment,
)

_TEXT_EXTENSIONS = {".txt", ".md", ".json", ".csv", ".yml", ".yaml", ".log",
                    ".srt", ".vtt", ".xml", ".py", ".js", ".ts", ".html", ".css"}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".avif"}


def default_input_dir() -> Optional[str]:
    """ComfyUI input 目录（真实环境经 folder_paths；测试环境回退到 cwd）。"""
    import os
    env = os.environ.get("COMFYUI_INPUT_DIR")
    if env and os.path.isdir(env):
        return env
    try:
        import folder_paths
        return folder_paths.get_input_directory()
    except Exception:  # noqa: BLE001 - 非 ComfyUI 环境
        return os.getcwd()


def _resolve_safe(raw_path: str, base_dir: Optional[str]) -> Optional[Path]:
    """把用户给的路径安全解析到 base_dir（ComfyUI input 目录）内。

    规则：相对路径以 base_dir 为基准解析；绝对路径/.. 逃逸后必须仍位于
    base_dir 之下；拒绝任何解析到 base 之外的路径。
    """
    raw = (raw_path or "").strip().strip('"')
    if not raw:
        return None
    base = Path(base_dir).resolve() if base_dir else None
    raw_obj = Path(raw).expanduser()
    if os.path.isabs(raw) or raw_obj.is_absolute():
        candidate = raw_obj.resolve()
    elif base is not None:
        candidate = (base / raw_obj).resolve()
    else:
        candidate = raw_obj.resolve()
    if base is not None:
        try:
            candidate.relative_to(base)
        except ValueError:
            return None
    if not candidate.is_file():
        return None
    return candidate


def _read_attachment(path: Path) -> Attachment:
    size = path.stat().st_size
    ext = path.suffix.lower()
    name = path.name
    mime, _ = mimetypes.guess_type(name)
    if ext in _TEXT_EXTENSIONS or (mime or "").startswith("text/"):
        if size > MAX_TEXT_BYTES:
            return Attachment(kind="text", name=name, mime_type=mime or "text/plain",
                              size_bytes=size,
                              problems=[f"文本附件超过大小上限（{MAX_TEXT_BYTES} 字节）"])
        data = path.read_bytes()
        return Attachment(kind="text", name=name, mime_type=mime or "text/plain",
                          content=data.decode("utf-8", errors="replace"),
                          size_bytes=size, source=f"file:{name}")
    if ext in _IMAGE_EXTENSIONS or (mime or "").startswith("image/"):
        if size > MAX_IMAGE_BYTES:
            return Attachment(kind="image", name=name, mime_type=mime or "image/png",
                              size_bytes=size,
                              problems=[f"图片附件超过大小上限（{MAX_IMAGE_BYTES} 字节）"])
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        return Attachment.from_base64(b64, name=name,
                                      mime_type=mime or "image/png")
    # 其他文件：作为文件附件（发送 file 内容部分；无能力时按降级规则处理）
    if size > MAX_FILE_BYTES:
        return Attachment(kind="file", name=name, mime_type=mime or "application/octet-stream",
                          size_bytes=size,
                          problems=[f"文件附件超过大小上限（{MAX_FILE_BYTES} 字节）"])
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return Attachment.from_base64(b64, name=name,
                                  mime_type=mime or "application/octet-stream")


def load_path_attachments(paths_text: str,
                          base_dir: Optional[str] = None) -> Tuple[List[Attachment], List[str]]:
    """把多行文件路径解析为附件列表（安全）。返回 (attachments, warnings)。"""
    attachments: List[Attachment] = []
    warnings: List[str] = []
    for line in (paths_text or "").splitlines():
        path = _resolve_safe(line, base_dir)
        if path is None:
            warnings.append(f"附件路径不可访问或越界，已跳过：{line.strip()!r}")
            continue
        att = _read_attachment(path)
        if att.problems:
            warnings.append(f"附件 {att.name} 校验失败：{'；'.join(att.problems)}，已跳过")
            continue
        attachments.append(att)
    return attachments, warnings


def gate_attachments(attachments: List[Attachment], caps: dict,
                     supports_vision: bool, supports_files: bool) -> Tuple[List[Attachment], List[str], Optional[str]]:
    """能力门槛：返回 (可发送列表, warnings, error_text)。

    有图片/文件附件无法发送时返回 error_text（调用方应报错，绝不静默成功）。
    """
    if not attachments:
        return [], [], None
    sendable: List[Attachment] = []
    warnings: List[str] = []
    errors: List[str] = []
    vision_ok = bool(supports_vision or caps.get("vision") is True)
    files_ok = bool(supports_files or caps.get("files") is True)

    for a in attachments:
        if a.kind == "text":
            sendable.append(a)
        elif a.kind == "image":
            if vision_ok:
                sendable.append(a)
            else:
                errors.append(
                    f"图片附件 {a.name!r} 无法发送：当前档案不支持视觉"
                    "（可配置视觉档案或开启档案高级设置 supports_vision）")
        elif a.kind == "file":
            if files_ok:
                sendable.append(a)
            else:
                # 降级：文件其实就是文本时已按 text 读取；走到这里是真正的二进制
                errors.append(
                    f"文件附件 {a.name!r} 无法发送：当前服务不支持文件内容部分"
                    "（可在档案高级设置开启 supports_files）")
    if errors:
        return sendable, warnings, "；".join(errors)
    return sendable, warnings, None


def text_context_for(attachments: List[Attachment]) -> str:
    """把文本附件拼成注入上下文的块（不进日志）。"""
    parts = []
    for a in attachments:
        if a.kind == "text" and a.content:
            parts.append(f"--- 附件 {a.name} ---\n{a.content}")
    return "\n\n".join(parts)

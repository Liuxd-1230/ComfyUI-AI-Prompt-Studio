"""本地运行时后端抽象与公共 HTTP 处理（独立服务，不加载进 ComfyUI 进程）。"""

from .base import RuntimeBackend, RuntimeFailure
from .custom import CustomHTTPBackend
from .llamacpp import LlamaCppBackend
from .lmstudio import LMStudioBackend
from .ollama import OllamaBackend

BACKEND_KINDS = {
    "ollama": OllamaBackend,
    "llamacpp": LlamaCppBackend,
    "lmstudio": LMStudioBackend,
    "custom": CustomHTTPBackend,
}


def create_backend(kind: str, url: str = "") -> RuntimeBackend:
    """按 kind 创建后端；未知 kind 抛 ValueError。url 为空用各后端默认地址。"""
    cls = BACKEND_KINDS.get(kind)
    if cls is None:
        raise ValueError(f"未知运行时后端 {kind!r}（可选：ollama/llamacpp/lmstudio/custom）")
    return cls(url or cls.default_url)


__all__ = [
    "RuntimeBackend", "RuntimeFailure", "OllamaBackend", "LlamaCppBackend",
    "LMStudioBackend", "CustomHTTPBackend", "create_backend", "BACKEND_KINDS",
]

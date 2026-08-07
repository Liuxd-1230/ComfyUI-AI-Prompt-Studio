"""LLM 统一结果结构：LLMResult / ChatSession / 附属类型。"""


import dataclasses
import time
import uuid
from typing import Any, Dict, List, Optional

from .base import Schema


@dataclasses.dataclass
class Usage(Schema):
    """token 用量（兼容 Responses / Chat Completions 的字段差异）。"""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0
    reasoning_tokens: int = 0
    extra: Dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class Citation(Schema):
    """联网搜索引用条目。"""

    index: int = 0
    url: str = ""
    title: str = ""
    snippet: str = ""


@dataclasses.dataclass
class ToolCall(Schema):
    """一次工具调用（function 或 web_search）。"""

    id: str = ""
    name: str = ""
    type: str = "function"          # function | web_search
    arguments: str = ""             # JSON 字符串
    output: str = ""                # 工具返回内容
    state: str = "completed"        # completed | in_progress | searching


@dataclasses.dataclass
class ErrorInfo(Schema):
    """结构化错误信息。错误绝不伪装成普通模型回答。"""

    kind: str = "unknown"           # 见 ERROR_KINDS
    message: str = ""
    http_status: int = 0
    retryable: bool = False
    degraded: bool = False          # 是否因降级链产生

    @property
    def as_text(self) -> str:
        if self.http_status:
            return f"[{self.kind}][HTTP {self.http_status}] {self.message}"
        return f"[{self.kind}] {self.message}"


ERROR_KINDS = {
    "auth_error": ("认证失败（401）", False),
    "forbidden": ("无权限（403）", False),
    "insufficient_balance": ("余额不足（402）", False),
    "rate_limit": ("限流（429）", False),
    "invalid_request": ("请求无效（400/422）", False),
    "context_overflow": ("上下文溢出", False),
    "server_error": ("服务器错误（5xx）", False),
    "network_error": ("网络连接失败", False),
    "timeout": ("请求超时", True),
    "protocol_unsupported": ("接口/参数不支持（可降级）", True),
    "vision_unsupported": ("模型无视觉能力", False),
    "canceled": ("已取消", False),
    "unknown": ("未知错误", False),
}


def make_error(kind: str, message: str = "", http_status: int = 0) -> ErrorInfo:
    label, _ = ERROR_KINDS.get(kind, ("未知错误", False))
    return ErrorInfo(kind=kind, message=message or label, http_status=http_status)


@dataclasses.dataclass
class LLMResult(Schema):
    """Gateway 的统一输出。text 永远只承载模型回答；错误在 error 字段。"""

    text: str = ""
    reasoning: str = ""
    citations: List[Citation] = dataclasses.field(default_factory=list)
    tool_calls: List[ToolCall] = dataclasses.field(default_factory=list)
    usage: Usage = dataclasses.field(default_factory=Usage)
    response_id: str = ""
    warnings: List[str] = dataclasses.field(default_factory=list)
    error: Optional[ErrorInfo] = None
    protocol: str = ""              # responses | chat_completions
    model: str = ""
    profile_id: str = ""
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    def has_error(self) -> bool:
        return self.error is not None

    def citations_as_text(self) -> str:
        return "\n".join(f"[{c.index}] {c.title or c.url}" for c in self.citations)

    def usage_as_text(self) -> str:
        return (
            f"in={self.usage.input_tokens} out={self.usage.output_tokens} "
            f"reasoning={self.usage.reasoning_tokens} "
            f"cache_hit={self.usage.prompt_cache_hit_tokens} "
            f"cache_miss={self.usage.prompt_cache_miss_tokens}"
        )


def empty_llm_result(profile_id: str = "", warnings: Optional[List[str]] = None) -> LLMResult:
    """节点骨架/未配置时的空结果，不伪装成模型回答。"""
    return LLMResult(profile_id=profile_id, warnings=list(warnings or []))


@dataclasses.dataclass
class ChatMessage(Schema):
    """会话中的一条消息。"""

    role: str = "user"              # system | user | assistant | tool | developer
    content: str = ""
    name: str = ""
    tool_call_id: str = ""
    tool_calls: List[ToolCall] = dataclasses.field(default_factory=list)
    reasoning: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")


@dataclasses.dataclass
class ChatSession(Schema):
    """多轮对话会话。to_api_messages() 生成协议无关的消息列表。"""

    id: str = ""
    profile_id: str = ""
    model: str = ""
    messages: List[ChatMessage] = dataclasses.field(default_factory=list)
    total_usage: Usage = dataclasses.field(default_factory=Usage)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        if not self.id:
            self.id = "sess_" + uuid.uuid4().hex[:12]
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def touch(self) -> None:
        self.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    def append(self, message: ChatMessage) -> None:
        self.messages.append(message)
        self.touch()

    def as_dict(self) -> Dict[str, Any]:
        return self.to_json()

    @classmethod
    def from_payload(cls, data: Any) -> "ChatSession":
        return cls.from_json(data)

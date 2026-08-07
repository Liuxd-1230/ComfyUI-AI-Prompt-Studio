"""协议适配器：Responses / Chat Completions（见 docs/research.md 接口核实）。"""

from .chat_adapter import ChatCompletionsAdapter
from .responses_adapter import ResponsesAdapter

__all__ = ["ChatCompletionsAdapter", "ResponsesAdapter"]

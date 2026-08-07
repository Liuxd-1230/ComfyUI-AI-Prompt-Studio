"""统一 LLM 网关：按档案/能力路由协议、处理搜索策略、执行降级链、归一化错误。

决策（docs/decisions.md D6/D7、docs/research.md）：
- 协议选择：profile.protocol=auto 时按能力缓存与 provider 决定（responses / chat_completions）；
- 只有 ProtocolUnsupported（接口/参数不支持）降级重试到另一协议，带警告；
- 401/402/403/429/5xx/网络失败/超时/取消 → 结构化 ErrorInfo，不重试、不伪装；
- POST 生成请求不自动重试（防重复扣费）；取消通过 stop_event 轮询。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..schemas.profile import AIProfile
from ..schemas.results import ChatMessage, LLMResult, make_error
from ..server.config_store import ConfigStore
from . import capability_probe, search
from .adapters.base import ProtocolUnsupported
from .adapters.chat_adapter import ChatCompletionsAdapter
from .adapters.responses_adapter import ResponsesAdapter

logger = logging.getLogger("ai_prompt_studio.gateway")


@dataclass
class GenerateRequest:
    """一次生成请求（协议无关）。"""

    system: str = ""
    messages: List[ChatMessage] = field(default_factory=list)
    web_search: str = "off"          # off | auto | always
    reasoning: str = "high"
    max_tokens: int = 4096
    temperature: float = 1.0
    json_mode: bool = False
    stop_event: Any = None
    timeout: float = 120.0


class Gateway:
    """统一网关。构造时可注入 store（默认用全局单例）。"""

    def __init__(self, store: Optional[ConfigStore] = None):
        self._store = store
        self._responses = ResponsesAdapter()
        self._chat = ChatCompletionsAdapter()

    @property
    def store(self) -> ConfigStore:
        if self._store is None:
            from ..server.config_store import get_store

            self._store = get_store()
        return self._store

    # ------------------------------------------------------------ 协议选择
    def _select_protocol(self, profile: AIProfile) -> str:
        if profile.protocol != "auto":
            return profile.protocol
        if profile.provider == "local":
            return "chat_completions"
        caps = self.store.get_capabilities(profile.profile_id)
        r = caps.get("responses")
        if r is True:
            return "responses"
        if r in ("unknown", None):
            # 未探测/未知：DeepSeek 按「具体模型」能力表兜底（flash→responses，
            # v4-pro→chat，未知模型保守走 chat；失败仍可被 ProtocolUnsupported 降级）
            if profile.provider == "deepseek":
                known = capability_probe.deepseek_known_responses(profile.model)
                if known is True:
                    return "responses"
                if known is False:
                    return "chat_completions"
            return "chat_completions"
        return "chat_completions"

    # ------------------------------------------------------------ 主入口
    def generate(self, profile: AIProfile, api_key: str, req: GenerateRequest) -> LLMResult:
        strategy = search.resolve_search_strategy(
            profile, self.store.get_capabilities(profile.profile_id), req.web_search)
        warnings: List[str] = []
        if strategy.get("warning"):
            warnings.append(strategy["warning"])
        web_search = bool(strategy.get("enabled") and strategy.get("native"))

        protocol = self._select_protocol(profile)
        try:
            result = self._call(profile, api_key, protocol, req, web_search=web_search)
        except ProtocolUnsupported as exc:
            # 仅「协议/参数不支持」降级到另一协议；其余异常已在 adapter 内归一化
            other = "chat_completions" if protocol == "responses" else "responses"
            warnings.append(f"协议 {protocol} 不可用（{exc}），已降级到 {other}")
            logger.info("gateway 降级 %s -> %s（%s）", protocol, other, exc)
            try:
                result = self._call(profile, api_key, other, req, web_search=web_search)
            except ProtocolUnsupported as exc2:
                return LLMResult(profile_id=profile.profile_id, model=profile.model,
                                 protocol=protocol,
                                 error=make_error(
                                     "protocol_unsupported",
                                     f"{protocol} 与 {other} 均不可用：{exc2}"),
                                 warnings=warnings)
        result.warnings = warnings + result.warnings
        return result

    def _call(self, profile, api_key, protocol, req: GenerateRequest, *,
              web_search: bool) -> LLMResult:
        if protocol == "responses":
            return self._responses.generate(
                profile, api_key, system=req.system, messages=req.messages,
                web_search=web_search, reasoning=req.reasoning,
                max_tokens=req.max_tokens, temperature=req.temperature,
                stop_event=req.stop_event, timeout=req.timeout)
        return self._chat.generate(
            profile, api_key, system=req.system, messages=req.messages,
            web_search=web_search, reasoning=req.reasoning,
            max_tokens=req.max_tokens, temperature=req.temperature,
            json_mode=req.json_mode, stop_event=req.stop_event, timeout=req.timeout)

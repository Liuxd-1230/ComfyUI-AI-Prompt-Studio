"""统一 LLM 网关：按档案/能力路由协议、处理搜索策略、执行降级链、归一化错误。

决策（docs/decisions.md D6/D7、docs/research.md）：
- 协议选择：profile.protocol=auto 时按能力缓存与 provider 决定（responses / chat_completions）；
- 只有 ProtocolUnsupported（接口/参数不支持）降级重试到另一协议，带警告；
- 401/402/403/429/5xx/网络失败/超时/取消 → 结构化 ErrorInfo，不重试、不伪装；
- POST 生成请求不自动重试（防重复扣费）；取消通过 stop_event 轮询；
- 联网搜索降级链：原生 web_search → 外部搜索后端（档案 search_url）→ 离线 + 明确警告；
- 函数工具执行循环：最多 MAX_TOOL_ROUNDS 轮（P1，不在节点 UI 暴露上限）；
- 本地运行时卸载策略（unload_policy）：after_request/after_success 由网关在请求后执行。
"""
from __future__ import annotations

import dataclasses
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..schemas.profile import AIProfile
from ..schemas.results import ChatMessage, LLMResult, make_error
from ..server.config_store import ConfigStore
from . import attachments as attachments_svc
from . import capability_probe, search, tools as tools_svc
from .adapters.base import ProtocolUnsupported
from .adapters.chat_adapter import ChatCompletionsAdapter
from .adapters.responses_adapter import ResponsesAdapter
from .runtime.control import run_runtime_action
from .tools import MAX_TOOL_ROUNDS

logger = logging.getLogger("ai_prompt_studio.gateway")


@dataclass
class GenerateRequest:
    """一次生成请求（协议无关）。

    采样参数为 None 时不在请求中发送该字段（交给 provider 默认值）——
    产品决策：采样参数不进普通节点 UI，只在档案高级设置里配置。
    """

    system: str = ""
    messages: List[ChatMessage] = field(default_factory=list)
    web_search: str = "off"          # off | auto | always
    reasoning: str = "high"
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    json_mode: bool = False
    output_schema: Optional[Dict[str, Any]] = None   # JSON Schema dict（结构化输出）
    attachments: List = field(default_factory=list)   # List[Attachment]（已过能力门槛）
    tools: bool = False             # 启用函数工具（P1；上限 MAX_TOOL_ROUNDS 不暴露到 UI）
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

        # 外部搜索后端（C4）：无原生 web_search 但配置了 search_url → 注入联网结果；
        # 失败 → 明确警告并降级为离线执行，绝不伪造结果
        if strategy.get("enabled") and not strategy.get("native"):
            ext = self._inject_external_search(profile, req)
            if ext.get("warning"):
                warnings.append(ext["warning"])

        # 附件能力门槛：失败即报错（不静默丢弃伪装成功）
        if req.attachments:
            caps = self.store.get_capabilities(profile.profile_id)
            sendable, att_warnings, att_error = attachments_svc.gate_attachments(
                req.attachments, caps, profile.supports_vision,
                profile.supports_files)
            warnings.extend(att_warnings)
            if att_error:
                return LLMResult(profile_id=profile.profile_id, model=profile.model,
                                 error=make_error("attachment_unsupported", att_error),
                                 warnings=warnings)
            req.attachments = sendable

        protocol = self._select_protocol(profile)

        # 结构化输出（0.2.1 P0-3）：按「当前协议」判定原生支持——
        # responses → caps.structured_output_responses；chat → structured_output_chat。
        # 支持 → 协议层 schema（text.format / response_format json_schema）；
        # 否则 → 提示词约束 + json_mode 兜底（DeepSeek Chat 未文档化 json_schema）。
        output_schema = req.output_schema
        caps = self.store.get_capabilities(profile.profile_id)
        if output_schema and not capability_probe.supports_native_structured_output(
                profile, caps, protocol):
            schema_text = json.dumps(output_schema, ensure_ascii=False)
            req.system = (req.system or "") + (
                "\n\n[输出约束]\n必须输出合法的 JSON 对象，"
                f"严格符合以下 JSON Schema：\n{schema_text}")
            req.json_mode = True
            output_schema = None

        tool_defs = tools_svc.tool_definitions() if req.tools else []

        try:
            result = self._call_with_tools(
                profile, api_key, protocol, req, web_search=web_search,
                output_schema=output_schema, tool_defs=tool_defs)
        except ProtocolUnsupported as exc:
            # 仅「协议/参数不支持」降级到另一协议；其余异常已在 adapter 内归一化
            other = "chat_completions" if protocol == "responses" else "responses"
            warnings.append(f"协议 {protocol} 不可用（{exc}），已降级到 {other}")
            logger.info("gateway 降级 %s -> %s（%s）", protocol, other, exc)
            try:
                result = self._call_with_tools(
                    profile, api_key, other, req, web_search=web_search,
                    output_schema=output_schema, tool_defs=tool_defs)
            except ProtocolUnsupported as exc2:
                return LLMResult(profile_id=profile.profile_id, model=profile.model,
                                 protocol=protocol,
                                 error=make_error(
                                     "protocol_unsupported",
                                     f"{protocol} 与 {other} 均不可用：{exc2}"),
                                 warnings=warnings)

        self._apply_unload_policy(profile, result)
        result.warnings = warnings + result.warnings
        return result

    def _call_with_tools(self, profile, api_key, protocol, req: GenerateRequest, *,
                         web_search: bool, output_schema: Optional[Dict[str, Any]] = None,
                         tool_defs: Optional[List[Dict[str, Any]]] = None) -> LLMResult:
        """一次协议调用；请求启用工具时循环执行 tool_calls（上限 MAX_TOOL_ROUNDS）。

        工具执行失败不抛异常：错误作为工具输出回给模型继续（模型可重试或停止）；
        达到轮数上限仍有 tool_calls → 追加截断警告（不静默丢弃）。
        """
        rounds = 0
        result = self._call(profile, api_key, protocol, req,
                            web_search=web_search, output_schema=output_schema,
                            tool_defs=tool_defs or [])
        while (req.tools and result.tool_calls
               and not result.has_error()
               and rounds < MAX_TOOL_ROUNDS):
            rounds += 1
            messages = list(req.messages)
            # 助手消息携带 tool_calls（供协议续轮）
            messages.append(ChatMessage(role="assistant", content=result.text,
                                        tool_calls=list(result.tool_calls)))
            for tc in result.tool_calls:
                out = tools_svc.execute_tool(tc.name, tc.arguments, profile)
                messages.append(ChatMessage(
                    role="tool", content=json.dumps(out, ensure_ascii=False),
                    tool_call_id=tc.id))
            req = dataclasses.replace(req, messages=messages)
            result = self._call(profile, api_key, protocol, req,
                                web_search=web_search, output_schema=output_schema,
                                tool_defs=tool_defs or [])
        if req.tools and result.tool_calls and not result.has_error() \
                and rounds >= MAX_TOOL_ROUNDS:
            result.warnings.append(
                f"工具调用已达上限（{MAX_TOOL_ROUNDS} 轮），已停止继续调用工具")
        return result

    def _inject_external_search(self, profile: AIProfile,
                                req: GenerateRequest) -> Dict[str, Any]:
        """外部搜索后端注入（C4）。

        查询取最后一条 user 消息（截断）；成功 → 结果块追加到该消息；
        失败 → 返回 warning（不伪造结果）。未配置 search_url → 提示配置。
        """
        url = (profile.search_url or "").strip()
        if not url:
            return {"warning": search.offline_result(profile.profile_id, "")["warning"]}
        query = ""
        for m in reversed(req.messages):
            if m.role == "user" and m.content.strip():
                query = m.content.strip()[:300]
                break
        if not query:
            return {"warning": "外部搜索未执行：请求中没有可用的用户消息作为查询词"}
        res = search.search_external(url, query)
        if not res.get("ok"):
            return {"warning": f"外部搜索失败（{res.get('error')}），"
                               "本请求将不带联网结果执行（结果可能不含最新信息）"}
        block = f"[联网搜索结果（查询：{query}）]\n" + search.format_results(res["results"])
        if req.messages and req.messages[-1].role == "user":
            req.messages[-1].content = (req.messages[-1].content or "") + "\n\n" + block
        else:
            req.messages.append(ChatMessage(role="user", content=block))
        return {"warning": ""}

    def _apply_unload_policy(self, profile: AIProfile, result: LLMResult) -> None:
        """C2：本地运行时卸载策略（never / after_request / after_success，仅 local）。

        after_request=请求结束即卸载（无论成败）；after_success=仅成功时卸载。
        卸载失败 → 追加 warning（不伪装成功、不影响请求结果）。
        """
        policy = (profile.unload_policy or "never")
        if profile.provider != "local" or policy == "never":
            return
        if policy == "after_success" and result.has_error():
            return
        runtime = profile.runtime or {}
        backend = runtime.get("backend") or "ollama"
        url = runtime.get("url") or ""
        model = runtime.get("model") or profile.model
        if not model:
            return
        try:
            res = run_runtime_action(backend, "unload", url, model)
        except Exception as exc:  # noqa: BLE001 - 卸载失败不应让请求失败
            result.warnings.append(f"unload_policy 卸载失败：{exc}")
            return
        if not res.get("ok"):
            result.warnings.append(f"unload_policy 卸载失败：{res.get('error')}")

    def _call(self, profile, api_key, protocol, req: GenerateRequest, *,
              web_search: bool, output_schema: Optional[Dict[str, Any]] = None,
              tool_defs: Optional[List[Dict[str, Any]]] = None) -> LLMResult:
        if protocol == "responses":
            return self._responses.generate(
                profile, api_key, system=req.system, messages=req.messages,
                web_search=web_search, reasoning=req.reasoning,
                max_tokens=req.max_tokens, temperature=req.temperature,
                attachments=req.attachments, output_schema=output_schema,
                tool_defs=tool_defs,
                stop_event=req.stop_event, timeout=req.timeout)
        return self._chat.generate(
            profile, api_key, system=req.system, messages=req.messages,
            web_search=web_search, reasoning=req.reasoning,
            max_tokens=req.max_tokens, temperature=req.temperature,
            json_mode=req.json_mode, attachments=req.attachments,
            output_schema=output_schema, tool_defs=tool_defs,
            stop_event=req.stop_event, timeout=req.timeout)

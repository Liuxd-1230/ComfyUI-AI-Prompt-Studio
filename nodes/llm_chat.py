"""节点 2：LLM Generate / Chat —— 通用文本生成、多轮对话、联网搜索、结构化输出。

经统一 Gateway（services/gateway.py）路由 Responses / Chat Completions 协议；
密钥由后端按 profile_id 解析，本节点与工作流 JSON 永不含密钥。
"""
from __future__ import annotations

import json

from ..schemas import types
from ..schemas.profile import AIProfile
from ..schemas.results import ChatMessage, ChatSession
from ..services.gateway import Gateway, GenerateRequest
from ._helpers import require_api_key, resolve_profile

HISTORY_MODES = ["append", "replace", "off"]
OUTPUT_MODES = ["text", "json", "json_schema"]

MAX_TOKENS_LEVELS = ["512", "1024", "2048", "4096", "8192"]


class APS_LLMGenerate:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "AI_PROFILE": (types.AI_PROFILE,),
            "system_prompt": ("STRING", {"default": "You are a helpful assistant.",
                                         "multiline": True, "tooltip": "系统提示词"}),
            "user_prompt": ("STRING", {"default": "", "multiline": True,
                                       "tooltip": "用户提示词"}),
            "context": ("STRING", {"default": "", "multiline": True,
                                   "tooltip": "附加上下文（文件/资料文本）注入到系统提示词"}),
            "max_tokens": (MAX_TOKENS_LEVELS, {"default": "4096",
                                               "tooltip": "最大输出 token 数"}),
        }, "optional": {
            "session": (types.CHAT_SESSION,),
            "history_mode": (HISTORY_MODES, {"default": "append",
                                             "tooltip": "append=追加到会话；replace=本请求替换会话历史；off=不记录历史"}),
            "output_mode": (OUTPUT_MODES, {"default": "text",
                                           "tooltip": "text=普通文本；json=强制 JSON 对象；json_schema=按下方 Schema 输出"}),
            "json_schema": ("STRING", {"default": "", "multiline": True,
                                       "tooltip": "可选 JSON Schema（output_mode=json_schema 时生效）"}),
        }}

    RETURN_TYPES = ("STRING", "STRING", types.CHAT_SESSION, types.LLM_RESULT, "STRING", "STRING", "STRING")
    RETURN_NAMES = ("text", "reasoning", "CHAT_SESSION", "LLM_RESULT", "citations", "usage", "warnings")
    FUNCTION = "generate"
    CATEGORY = "AI Prompt Studio"
    DESCRIPTION = "通用 LLM 生成/对话（Responses / Chat Completions / 联网搜索 / 工具调用 / 结构化输出）。"

    def generate(self, AI_PROFILE, system_prompt, user_prompt, context,
                 max_tokens="4096", session=None, history_mode="append",
                 output_mode="text", json_schema="", stop_event=None):
        profile = AIProfile.from_json(AI_PROFILE or {})
        if not profile.profile_id:
            raise ValueError("未收到 AI_PROFILE：请先连接 AI Model Profile 节点并选择档案")
        prof = resolve_profile(profile.profile_id)
        api_key = require_api_key(prof)

        user_text = (user_prompt or "").strip()
        ctx_text = (context or "").strip()
        if not user_text and not ctx_text:
            raise ValueError("user_prompt 与 context 均为空，请至少填写一个")

        # 上下文注入系统提示词；历史按 history_mode 组装
        system = system_prompt or "You are a helpful assistant."
        if ctx_text:
            system = f"{system}\n\n[附加上下文]\n{ctx_text}"

        sess = ChatSession.from_payload(session) if session else ChatSession(
            profile_id=prof.profile_id, model=prof.model)
        sess.profile_id = prof.profile_id
        sess.model = prof.model

        user_msg = ChatMessage(role="user", content=user_text or ctx_text)
        if history_mode == "append":
            messages = list(sess.messages)
            if messages and messages[-1].content == user_msg.content:
                pass  # 同一轮重复调用不重复追加用户消息
            else:
                messages.append(user_msg)
        else:  # replace / off：只发送当前轮
            messages = [user_msg]

        if output_mode == "json_schema" and json_schema.strip():
            system = (f"{system}\n\n[输出约束]\n必须输出合法的 JSON 对象，"
                      f"严格符合以下 JSON Schema：\n{json_schema.strip()}")
        json_mode = output_mode in ("json", "json_schema")

        req = GenerateRequest(
            system=system,
            messages=messages,
            web_search=prof.web_search,
            reasoning=prof.reasoning,
            max_tokens=int(max_tokens or 4096),
            temperature=1.0,
            json_mode=json_mode,
            stop_event=stop_event,
            timeout=prof.timeout,
        )
        result = Gateway().generate(prof, api_key, req)

        if result.has_error():
            raise ValueError(result.error.as_text)

        # 会话更新
        if history_mode != "off":
            if not (sess.messages and sess.messages[-1].content == user_msg.content):
                sess.append(user_msg)
            sess.append(ChatMessage(role="assistant", content=result.text,
                                    reasoning=result.reasoning))
        sess.total_usage = _add_usage(sess.total_usage, result.usage)

        # JSON 输出校验
        warnings = list(result.warnings)
        if json_mode and result.text.strip():
            try:
                json.loads(result.text)
            except ValueError:
                warnings.append("模型输出不是合法 JSON，text 原样返回（可重试或改用 text 模式）")

        return (result.text, result.reasoning, sess.to_json(), result.to_json(),
                result.citations_as_text(), result.usage_as_text(), "\n".join(warnings))


def _add_usage(a, b):
    a.input_tokens += b.input_tokens
    a.output_tokens += b.output_tokens
    a.total_tokens += b.total_tokens
    a.reasoning_tokens += b.reasoning_tokens
    a.prompt_cache_hit_tokens += b.prompt_cache_hit_tokens
    a.prompt_cache_miss_tokens += b.prompt_cache_miss_tokens
    return a

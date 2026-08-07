"""节点 2：LLM Generate / Chat —— 通用文本生成、多轮对话、联网搜索、结构化输出。

Phase 1：注册与数据结构就绪；Phase 2 接入 Gateway 后完整实现。
"""

from ..schemas import types
from ..schemas.results import ChatSession, empty_llm_result

HISTORY_MODES = ["append", "replace", "off"]
OUTPUT_MODES = ["text", "json", "json_schema"]


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
                                   "tooltip": "附加上下文（文件/资料文本）注入"}),
        }, "optional": {
            "session": (types.CHAT_SESSION,),
            "history_mode": (HISTORY_MODES, {"default": "append",
                                             "tooltip": "append=追加到会话；replace=本请求替换会话；off=不记录历史"}),
            "output_mode": (OUTPUT_MODES, {"default": "text",
                                           "tooltip": "text=普通文本；json=JSON 对象；json_schema=按下方 Schema 输出"}),
            "json_schema": ("STRING", {"default": "", "multiline": True,
                                       "tooltip": "可选 JSON Schema（output_mode=json_schema 时生效）"}),
        }}

    RETURN_TYPES = ("STRING", "STRING", types.CHAT_SESSION, types.LLM_RESULT, "STRING", "STRING", "STRING")
    RETURN_NAMES = ("text", "reasoning", "CHAT_SESSION", "LLM_RESULT", "citations", "usage", "warnings")
    FUNCTION = "generate"
    CATEGORY = "AI Prompt Studio"
    DESCRIPTION = "通用 LLM 生成/对话（Responses / Chat Completions / 联网搜索 / 工具调用 / 结构化输出）。"

    def generate(self, AI_PROFILE, system_prompt, user_prompt, context,
                 session=None, history_mode="append", output_mode="text", json_schema=""):
        # Phase 2 接入 Gateway。当前返回骨架空结果，带明确警告，不伪装。
        profile_id = (AI_PROFILE or {}).get("profile_id", "")
        result = empty_llm_result(profile_id, warnings=["LLM Generate 功能将在 Phase 2 接入 Gateway"])
        sess = ChatSession.from_payload(session) if session else ChatSession(profile_id=profile_id)
        result_text = result.text
        return (result_text, result.reasoning, sess.to_json(), result.to_json(),
                result.citations_as_text(), result.usage_as_text(), "\n".join(result.warnings))

"""节点层测试：LLM Generate 与 Runtime Control 的完整接线（Gateway/后端 mock）。"""
import json

import pytest

import aps.nodes.llm_chat as llm_chat_mod
import aps.nodes.runtime_control as runtime_mod
from aps.schemas.profile import AIProfile
from aps.schemas.results import ChatSession, LLMResult, make_error


class FakeGateway:
    def __init__(self, result):
        self.result = result
        self.req = None
        self.profile = None

    def generate(self, profile, api_key, req):
        self.profile = profile
        self.req = req
        return self.result


def setup_profile(store, api_key="sk-abcdef1234567890"):
    store.create_profile({"profile_id": "p1", "name": "DeepSeek"})
    store.set_api_key("p1", api_key)
    return store.get_profile("p1").node_payload()


def test_llm_generate_happy_path(monkeypatch, store):
    payload = setup_profile(store)
    result = LLMResult(text="回答内容", reasoning="推理过程", profile_id="p1")
    result.usage.input_tokens = 7
    fake = FakeGateway(result)
    monkeypatch.setattr(llm_chat_mod, "Gateway", lambda: fake)

    node = llm_chat_mod.APS_LLMGenerate()
    out = node.generate(AI_PROFILE=payload, system_prompt="sys", user_prompt="问",
                        context="", session=None,
                        history_mode="append", output_mode="text", json_schema="")
    text, reasoning, sess_json, result_json, citations, usage, warnings = out
    assert text == "回答内容"
    assert reasoning == "推理过程"
    sess = ChatSession.from_json(sess_json)  # to_json() 直接输出 dict
    assert len(sess.messages) == 2  # user + assistant
    assert sess.messages[0].role == "user"
    assert sess.messages[1].content == "回答内容"
    llm = LLMResult.from_json(result_json)
    assert llm.text == "回答内容"
    assert "in=7" in usage
    assert warnings == ""


def test_llm_generate_explicit_markdown_supplement_enters_assembly(monkeypatch, store, tmp_path):
    from aps.services import supplements

    monkeypatch.setattr(supplements, "supplements_dir",
                        lambda: tmp_path / "prompt_supplements")
    record = supplements.import_supplement({
        "supplement_id": "llm-notes", "title": "LLM notes", "filename": "llm.md",
        "scope": "node", "node_ids": ["llm.generate"],
        "content": "Use concise bullet points.",
    })
    payload = setup_profile(store)
    fake = FakeGateway(LLMResult(text="ok", profile_id="p1"))
    monkeypatch.setattr(llm_chat_mod, "Gateway", lambda: fake)
    llm_chat_mod.APS_LLMGenerate().generate(
        AI_PROFILE=payload, system_prompt="", user_prompt="问", context="",
        history_mode="off", output_mode="text", json_schema="",
        prompt_supplements=record.supplement_id)
    assert "Use concise bullet points." in fake.req.system
    assert any(item["source_id"] == "supplement.llm-notes"
               for item in fake.req.assembly_report["sources"])


def test_llm_generate_uses_capable_default_system_prompt(monkeypatch, store):
    payload = setup_profile(store)
    fake = FakeGateway(LLMResult(text="ok", profile_id="p1"))
    monkeypatch.setattr(llm_chat_mod, "Gateway", lambda: fake)
    default = llm_chat_mod.APS_LLMGenerate.INPUT_TYPES()["required"]["system_prompt"][1]["default"]
    assert default == llm_chat_mod.DEFAULT_SYSTEM_PROMPT
    llm_chat_mod.APS_LLMGenerate().generate(
        AI_PROFILE=payload, system_prompt="", user_prompt="问", context="",
        history_mode="off", output_mode="text", json_schema="")
    assert llm_chat_mod.DEFAULT_SYSTEM_PROMPT in fake.req.system


def test_llm_generate_raises_on_error(monkeypatch, store):
    payload = setup_profile(store)
    result = LLMResult(profile_id="p1",
                       error=make_error("insufficient_balance", "余额不足", 402))
    monkeypatch.setattr(llm_chat_mod, "Gateway",
                        lambda: FakeGateway(result))
    node = llm_chat_mod.APS_LLMGenerate()
    with pytest.raises(ValueError, match="402"):
        node.generate(AI_PROFILE=payload, system_prompt="", user_prompt="问",
                      context="", session=None,
                      history_mode="append", output_mode="text", json_schema="")


def test_llm_generate_missing_api_key(store):
    store.create_profile({"profile_id": "p1"})
    payload = store.get_profile("p1").node_payload()
    node = llm_chat_mod.APS_LLMGenerate()
    with pytest.raises(ValueError, match="API Key"):
        node.generate(AI_PROFILE=payload, system_prompt="", user_prompt="问",
                      context="", session=None,
                      history_mode="append", output_mode="text", json_schema="")


def test_llm_generate_empty_prompt(store):
    payload = setup_profile(store)
    node = llm_chat_mod.APS_LLMGenerate()
    with pytest.raises(ValueError, match="为空"):
        node.generate(AI_PROFILE=payload, system_prompt="sys", user_prompt="",
                      context="", session=None,
                      history_mode="append", output_mode="text", json_schema="")


def test_llm_generate_json_mode_warns_on_bad_json(monkeypatch, store):
    payload = setup_profile(store)
    result = LLMResult(text="不是JSON", profile_id="p1")
    monkeypatch.setattr(llm_chat_mod, "Gateway", lambda: FakeGateway(result))
    node = llm_chat_mod.APS_LLMGenerate()
    _, _, _, _, _, _, warnings = node.generate(
        AI_PROFILE=payload, system_prompt="", user_prompt="问", context="",
        session=None, history_mode="off",
        output_mode="json", json_schema="")
    assert "不是合法 JSON" in warnings


def test_llm_generate_json_schema_sets_output_schema(monkeypatch, store):
    """合法 schema → 走 gateway 协议层（output_schema），system 不再内联拼接。"""
    payload = setup_profile(store)
    result = LLMResult(text='{"a": 1}', profile_id="p1")
    fake = FakeGateway(result)
    monkeypatch.setattr(llm_chat_mod, "Gateway", lambda: fake)
    node = llm_chat_mod.APS_LLMGenerate()
    node.generate(AI_PROFILE=payload, system_prompt="sys", user_prompt="问",
                  context="", session=None,
                  history_mode="off", output_mode="json_schema",
                  json_schema='{"type":"object"}')
    assert fake.req.output_schema == {"type": "object"}
    assert fake.req.json_mode is True
    assert "JSON Schema" not in fake.req.system


def test_llm_generate_json_schema_invalid_falls_back_to_constraint(monkeypatch, store):
    """非法 schema → 提示词约束兜底 + warning，不静默丢弃。"""
    payload = setup_profile(store)
    result = LLMResult(text='{"a": 1}', profile_id="p1")
    fake = FakeGateway(result)
    monkeypatch.setattr(llm_chat_mod, "Gateway", lambda: fake)
    node = llm_chat_mod.APS_LLMGenerate()
    _, _, _, _, _, _, warnings = node.generate(
        AI_PROFILE=payload, system_prompt="sys", user_prompt="问", context="",
        session=None, history_mode="off", output_mode="json_schema",
        json_schema='not-json')
    assert fake.req.output_schema is None
    assert "JSON Schema" in fake.req.system
    assert "不是合法 JSON 对象" in warnings


def test_llm_generate_history_off_keeps_session(monkeypatch, store):
    payload = setup_profile(store)
    result = LLMResult(text="hi", profile_id="p1")
    fake = FakeGateway(result)
    monkeypatch.setattr(llm_chat_mod, "Gateway", lambda: fake)
    sess = ChatSession(profile_id="p1")
    sess.append(llm_chat_mod.ChatMessage(role="user", content="旧消息"))
    node = llm_chat_mod.APS_LLMGenerate()
    _, _, sess_json, _, _, _, _ = node.generate(
        AI_PROFILE=payload, system_prompt="", user_prompt="新消息", context="",
        session=sess.to_json(), history_mode="off",
        output_mode="text", json_schema="")
    restored = ChatSession.from_json(sess_json)
    assert len(restored.messages) == 1  # off 不改动原会话


def test_llm_generate_replace_replaces_returned_history(monkeypatch, store):
    payload = setup_profile(store)
    fake = FakeGateway(LLMResult(text="新回答", profile_id="p1"))
    monkeypatch.setattr(llm_chat_mod, "Gateway", lambda: fake)
    sess = ChatSession(profile_id="p1")
    sess.append(llm_chat_mod.ChatMessage(role="user", content="旧消息"))
    out = llm_chat_mod.APS_LLMGenerate().generate(
        AI_PROFILE=payload, system_prompt="", user_prompt="新消息", context="",
        session=sess.to_json(), history_mode="replace", output_mode="text",
        json_schema="")
    restored = ChatSession.from_json(out[2])
    assert [m.content for m in restored.messages] == ["新消息", "新回答"]


def test_profile_node_overrides_and_sampling_reach_gateway(monkeypatch, store):
    store.create_profile({"profile_id": "p1", "model": "stored",
                          "top_p": 0.7, "frequency_penalty": 0.2,
                          "presence_penalty": -0.1})
    store.set_api_key("p1", "sk-test")
    payload = store.get_profile("p1").node_payload()
    payload.update({"model": "override", "protocol": "chat_completions",
                    "reasoning": "low", "web_search": "off",
                    "unload_policy": "after_request"})
    fake = FakeGateway(LLMResult(text="ok", profile_id="p1"))
    monkeypatch.setattr(llm_chat_mod, "Gateway", lambda: fake)
    llm_chat_mod.APS_LLMGenerate().generate(
        AI_PROFILE=payload, system_prompt="", user_prompt="x", context="",
        history_mode="off", output_mode="text", json_schema="")
    assert fake.profile.model == "override"
    assert fake.profile.unload_policy == "after_request"
    assert fake.req.top_p == 0.7
    assert fake.req.frequency_penalty == 0.2
    assert fake.req.presence_penalty == -0.1


def test_context_only_is_not_duplicated_as_user_instruction(monkeypatch, store):
    payload = setup_profile(store)
    fake = FakeGateway(LLMResult(text="ok", profile_id="p1"))
    monkeypatch.setattr(llm_chat_mod, "Gateway", lambda: fake)
    llm_chat_mod.APS_LLMGenerate().generate(
        AI_PROFILE=payload, system_prompt="", user_prompt="", context="DATA-ONLY",
        history_mode="off", output_mode="text", json_schema="")
    assert "DATA-ONLY" not in fake.req.system
    assert sum(message.content.count("DATA-ONLY") for message in fake.req.messages) == 1
    assert fake.req.messages[-1].content == "请根据上方附加上下文完成任务。"


def test_runtime_control_load(monkeypatch):
    class FakeBackend:
        kind = "ollama"
        default_url = "http://x"

        def load(self, model):
            return {"ok": True, "model": model, "detail": "已加载"}

        def status(self):
            return {"available": True, "models": ["m1"], "error": ""}

        def list_models(self):
            return ["m1"]

    # 节点经共享服务层调用 create_backend（services/runtime/control）
    from aps.services.runtime import control as runtime_ctrl
    monkeypatch.setattr(runtime_ctrl, "create_backend",
                        lambda kind, url: FakeBackend())
    node = runtime_mod.APS_RuntimeControl()
    _, status_json, loaded_json, op_json = node.control(
        backend="ollama", action="load", url="", model="m1", AI_PROFILE=None)
    op = json.loads(op_json)
    assert op["ok"] is True
    assert op["model"] == "m1"
    assert json.loads(status_json)["backend"] == "ollama"


def test_runtime_control_unknown_backend():
    node = runtime_mod.APS_RuntimeControl()
    _, _, _, op_json = node.control(backend="bogus", action="status",
                                    url="", model="", AI_PROFILE=None)
    op = json.loads(op_json)
    assert op["ok"] is False and "未知运行时后端" in op["error"]


def test_runtime_list_models_unavailable_is_not_false_success(monkeypatch):
    class OfflineBackend:
        def status(self):
            return {"available": False, "models": [], "error": "offline"}

        def list_models(self):
            raise AssertionError("offline 时不应继续列表请求")

    from aps.services.runtime import control as runtime_ctrl
    monkeypatch.setattr(runtime_ctrl, "create_backend", lambda *args: OfflineBackend())
    result = runtime_ctrl.run_runtime_action("ollama", "list_models")
    assert result["ok"] is False
    assert result["error"] == "offline"


def test_runtime_control_load_requires_model():
    node = runtime_mod.APS_RuntimeControl()
    _, _, _, op_json = node.control(backend="ollama", action="load", url="",
                                    model="", AI_PROFILE=None)
    op = json.loads(op_json)
    assert op["ok"] is False and "model" in op["error"]

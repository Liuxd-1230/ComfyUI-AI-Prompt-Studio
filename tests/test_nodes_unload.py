"""节点层测试：APS_UnloadModel（专用 LM Studio 卸载节点）的接线。

节点固定走 backend=lmstudio，经共享服务层 run_runtime_action 调用
create_backend（services/runtime/control），这里 mock 掉 create_backend，不触网。
"""
import json

import pytest

import aps.nodes.unload_model as unload_mod
from aps.services.runtime import control as runtime_ctrl


class FakeBackend:
    """仿 LMStudioBackend.unload 返回结构（{ok, model, instance_id, detail/error}）。"""

    def __init__(self, result):
        self._result = result
        self.called = False

    def unload(self, model):
        self.called = True
        return dict(self._result)


def patch_backend(monkeypatch, result):
    backend = FakeBackend(result)
    monkeypatch.setattr(runtime_ctrl, "create_backend",
                        lambda kind, url: backend)
    return backend


def test_unload_success(monkeypatch):
    patch_backend(monkeypatch, {
        "ok": True, "model": "openai/gpt-oss-20b",
        "instance_id": "inst-7", "detail": "已卸载"})
    node = unload_mod.APS_UnloadModel()
    prompt, result_json, status = node.unload(
        prompt="generated prompt", model="openai/gpt-oss-20b", url="")
    result = json.loads(result_json)
    assert prompt == "generated prompt"
    assert result["ok"] is True
    assert result["model"] == "openai/gpt-oss-20b"
    assert result["instance_id"] == "inst-7"
    assert result["error"] == ""
    assert status == "已卸载 openai/gpt-oss-20b"


def test_unload_empty_model(monkeypatch):
    class EmptyBackend(FakeBackend):
        def unload_all(self):
            self.called = True
            return {"ok": True, "unloaded": ["m1", "m2"], "error": ""}
    backend = EmptyBackend({})
    monkeypatch.setattr(runtime_ctrl, "create_backend", lambda kind, url: backend)
    node = unload_mod.APS_UnloadModel()
    prompt, result_json, status = node.unload(prompt="p", model="", url="")
    result = json.loads(result_json)
    assert prompt == "p"
    assert result["ok"] is True
    assert result["model"] == ""
    assert result["unloaded"] == ["m1", "m2"]
    assert "2 个" in status
    assert backend.called is True


def test_unload_backend_error(monkeypatch):
    patch_backend(monkeypatch, {
        "ok": False, "model": "m1",
        "error": "未找到模型 m1 的已加载实例（instance_id）；请先 load 或检查模型名"})
    node = unload_mod.APS_UnloadModel()
    with pytest.raises(RuntimeError, match="instance_id"):
        node.unload(prompt="p", model="m1", url="http://127.0.0.1:1234")


def test_unload_already_unloaded_passes_prompt(monkeypatch):
    patch_backend(monkeypatch, {
        "ok": True, "model": "m1", "already_unloaded": True,
        "instance_ids": [], "detail": "模型已处于卸载状态"})
    node = unload_mod.APS_UnloadModel()
    prompt, result_json, status = node.unload(prompt="p", model="m1", url="")
    result = json.loads(result_json)
    assert prompt == "p"
    assert result["ok"] is True
    assert result["already_unloaded"] is True
    assert status == "m1 已处于卸载状态"


def test_unload_unreachable(monkeypatch):
    # 真实路径：LMStudioBackend._request 把连接失败转成 {ok: False, error: 无法连接...}
    patch_backend(monkeypatch, {"ok": False, "model": "m1",
                                "error": "无法连接 http://127.0.0.1:1234：ConnectionError"})
    node = unload_mod.APS_UnloadModel()
    with pytest.raises(RuntimeError, match="无法连接"):
        node.unload(prompt="p", model="m1", url="")


def test_unload_fixed_backend_lmstudio():
    """节点固定 lmstudio，并以 prompt 输入/输出建立严格执行顺序。"""
    node = unload_mod.APS_UnloadModel()
    inputs = node.INPUT_TYPES()
    assert "model" in inputs["required"]
    assert "prompt" in inputs["optional"]
    assert inputs["optional"]["prompt"][1]["forceInput"] is True
    assert "backend" not in inputs["required"]
    assert "url" in inputs["optional"]
    assert node.RETURN_TYPES == ("STRING", "STRING", "STRING")
    assert node.RETURN_NAMES == ("prompt", "result", "status")
    assert node.OUTPUT_NODE is True
    assert node.IS_CHANGED("m1", "p") != node.IS_CHANGED("m1", "p")

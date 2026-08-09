"""冒烟：忠实复刻 ComfyUI 0.30.2 的 custom node 加载语义（nodes.py::load_custom_node）。

用户 ComfyUI 环境（standalone-env）当前缺少 torch 无法完整启动，故用等价的加载器语义验证：
- 目录节点：sys_module_name = module_path.replace(".", "_x_")
- spec_from_file_location(module_path/__init__.py) + sys.modules 注册 + exec
- WEB_DIRECTORY 注册前提（web 目录存在）
- V1 节点定义：NODE_CLASS_MAPPINGS 注册 + RELATIVE_PYTHON_MODULE 赋值
"""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

EXPECTED_NODES = [
    "APS_ModelProfile", "APS_LLMGenerate", "APS_ReferenceAnalyzer",
    "APS_CharacterBible", "APS_StoryboardBuilder", "APS_StoryboardSelect",
    "APS_PromptComposer", "APS_ReferencePrompt", "APS_MiniMaxH3Director", "APS_RuntimeControl",
    "APS_UnloadModel",
]


def _comfyui_load(module_path: str):
    """复刻 nodes.py::load_custom_node（目录节点分支）的加载逻辑。"""
    module_name = os.path.basename(module_path)
    sys_module_name = module_path.replace(".", "_x_")
    module_spec = importlib.util.spec_from_file_location(
        sys_module_name, os.path.join(module_path, "__init__.py"))
    module_dir = module_path
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[sys_module_name] = module
    module_spec.loader.exec_module(module)
    return module, module_name, module_dir


@pytest.fixture(scope="module")
def loaded():
    """以 ComfyUI 加载器语义加载本扩展一次。"""
    sys.path.insert(0, str(PROJECT_ROOT))
    return _comfyui_load(str(PROJECT_ROOT))


def test_loads_under_comfyui_loader(loaded):
    module, module_name, module_dir = loaded
    assert hasattr(module, "NODE_CLASS_MAPPINGS")
    assert hasattr(module, "NODE_DISPLAY_NAME_MAPPINGS")
    assert hasattr(module, "WEB_DIRECTORY")
    # 关键：ComfyUI 加载器要求相对导入在根 __init__.py 内可用（spec 加载即验证此点）
    assert len(module.NODE_CLASS_MAPPINGS) == 11
    assert module.WEB_DIRECTORY == "./web"


def test_node_registration_path_replicated(loaded):
    """复刻 nodes.py V1 注册段：映射 + RELATIVE_PYTHON_MODULE + WEB_DIRECTORY 目录。"""
    module, module_name, module_dir = loaded
    mappings = {}
    for name, node_cls in module.NODE_CLASS_MAPPINGS.items():
        mappings[name] = node_cls
        node_cls.RELATIVE_PYTHON_MODULE = "custom_nodes.{}".format(module_name)
    assert set(mappings.keys()) == set(EXPECTED_NODES)
    assert mappings["APS_ModelProfile"].RELATIVE_PYTHON_MODULE == \
        "custom_nodes.ComfyUI-AI-Prompt-Studio"

    web_dir = os.path.abspath(os.path.join(module_dir, module.WEB_DIRECTORY))
    assert os.path.isdir(web_dir)
    assert os.path.isfile(os.path.join(web_dir, "settings.js"))
    assert os.path.isfile(os.path.join(web_dir, "profile_widgets.js"))
    assert os.path.isfile(os.path.join(web_dir, "prompt_studio.js"))
    assert os.path.isfile(os.path.join(web_dir, "styles.css"))


def test_node_instances_instantiable(loaded):
    """节点类可实例化且 INPUT_TYPES()/RETURN_TYPES 完整（与真实 ComfyUI 校验一致）。"""
    module, _, _ = loaded
    for name in EXPECTED_NODES:
        cls = module.NODE_CLASS_MAPPINGS[name]
        node = cls()
        assert node is not None
        it = cls.INPUT_TYPES()
        assert "required" in it
        assert cls.FUNCTION and hasattr(cls, cls.FUNCTION)


def test_chinese_help_mentions_every_public_node_port(loaded):
    """节点接口变化时，中文帮助必须同步每一个公开输入和输出。"""
    module, _, _ = loaded
    for node_name, node_class in module.NODE_CLASS_MAPPINGS.items():
        help_path = PROJECT_ROOT / "web" / "docs" / node_name / "zh.md"
        assert help_path.exists(), f"{node_name} 缺少中文帮助"
        text = help_path.read_text(encoding="utf-8")
        inputs = node_class.INPUT_TYPES()
        port_names = set(inputs.get("required", {})) | set(inputs.get("optional", {}))
        port_names.update(getattr(node_class, "RETURN_NAMES", ()))
        missing = sorted(name for name in port_names if name not in text)
        assert not missing, f"{node_name} 中文帮助未说明端口: {missing}"


def test_settings_editor_exposes_saved_key_state():
    """密码框不能回填明文，但编辑器必须明确显示服务端的保存状态。"""
    source = (PROJECT_ROOT / "web" / "settings.js").read_text(encoding="utf-8")
    assert "has_api_key" in source
    assert "aps-key-status" in source
    helper = (PROJECT_ROOT / "web" / "profile_widgets.js").read_text(encoding="utf-8")
    assert 'typeof v === "boolean" && k in node' in helper


def test_prompt_studio_frontend_persists_backend_session_in_widget():
    source = (PROJECT_ROOT / "web" / "prompt_studio.js").read_text(encoding="utf-8")
    assert 'byName(node, "prompt_session")' in source
    assert "onExecuted" in source
    assert "message.prompt_session" in source
    assert "current_prompt" in source
    assert "aps-studio-input" in source
    assert 'setWidget(node, "text", chatInput.value)' in source
    assert 'addEventListener("execution_error"' in source
    assert 'classList.remove("is-error")' in source
    assert "继续上次方案" not in source
    assert 'hideSerializedWidget(byName(node, name))' in source
    assert "新会话" in source and "恢复上一版为新版本" in source
    new_action = source[source.index("data-action=\"new\""):source.index(
        "return root;", source.index("data-action=\"new\""))]
    assert 'setWidget(node, "prompt_session", "")' not in new_action
    assert "旧会话会保留到新结果成功提交" in new_action


def test_binding_refactor_contracts_are_present_and_referenced():
    """Architecture work must not silently lose its durable repository contract."""
    agents = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    contract_dir = PROJECT_ROOT / "docs" / "重构约束"
    names = (
        "APS_Persistent_Semantic_Architecture_Agent_Prompt.md",
        "APS_Whole_Library_Prompt_Architecture_Agent_Prompt.md",
    )
    for name in names:
        path = contract_dir / name
        assert path.exists(), f"缺少重构约束：{name}"
        assert path.stat().st_size > 50_000, f"重构约束疑似被占位或截断：{name}"
        assert name in agents, f"AGENTS.md 未强制引用重构约束：{name}"


def test_session_widgets_are_appended_after_legacy_serialized_widgets(loaded):
    """旧 workflow 的 widget_values 是位置数组；新字段只能追加，不能插队。"""
    module, _, _ = loaded
    composer = list(module.NODE_CLASS_MAPPINGS["APS_PromptComposer"].INPUT_TYPES()["optional"])
    assert composer.index("content_tier") < composer.index("continue_previous")
    assert composer[-4:] == ["continue_previous", "prompt_session", "session_action",
                             "message_nonce"]
    h3 = list(module.NODE_CLASS_MAPPINGS["APS_MiniMaxH3Director"].INPUT_TYPES()["optional"])
    assert h3[-4:] == ["continue_previous", "prompt_session", "session_action",
                       "message_nonce"]

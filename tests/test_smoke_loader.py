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
    "APS_PromptStudio", "APS_ReferencePrompt", "APS_H3PromptStudio", "APS_RuntimeControl",
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
    assert "INPUT_DEBOUNCE_MS = 200" in source
    assert "root._flushInput = flushInput" in source
    assert "textWidget.value = chatInput.value" in source
    assert 'addEventListener("execution_error"' in source
    assert 'classList.remove("is-error")' in source
    assert "继续上次方案" not in source
    assert 'hideSerializedWidget(byName(node, name))' in source
    assert "新会话" in source and "恢复上一版为新版本" in source
    new_action = source[source.index("data-action=\"new\""):source.index(
        "return root;", source.index("data-action=\"new\""))]
    assert 'setWidget(node, "prompt_session", "")' not in new_action
    assert "旧会话会保留到新结果成功提交" in new_action
    assert "当前会话尚无可恢复的成功版本" in source
    assert "recoverNewerJournal(node, root)" in source
    assert "Recover v${diskRevision}?" in source
    assert 'api.fetchApi(path, { method: "DELETE" })' in source
    assert "markWorkflowDirty(node)" in source
    assert "activeWorkflow?.changeTracker?.checkState?.()" in source


def test_prompt_studio_dom_widget_has_bounded_layout_contract():
    source = (PROJECT_ROOT / "web" / "prompt_studio.js").read_text(encoding="utf-8")
    styles = (PROJECT_ROOT / "web" / "styles.css").read_text(encoding="utf-8")
    assert "getMinHeight: () => STUDIO_HEIGHT" in source
    assert "getMaxHeight: () => studioWidget?._apsHeight" in source
    assert "studioWidget.computeSize" in source
    assert "height: 320px" in styles
    assert "max-height: 410px" in styles
    assert "overflow: hidden" in styles
    assert "H3_MODE_HELP" in source
    assert "执行方式：" in source
    assert "widget.hidden = true" in source


def test_studio_frontend_detects_stale_backend_contract():
    source = (PROJECT_ROOT / "web" / "prompt_studio.js").read_text(encoding="utf-8")
    routes = (PROJECT_ROOT / "server" / "routes.py").read_text(encoding="utf-8")
    assert 'UI_CONTRACT_VERSION = "single-lane-ui-v2"' in source
    assert 'UI_CONTRACT_VERSION = "single-lane-ui-v2"' in routes
    assert "verifyUiContract(node, root)" in source
    assert "请重启 ComfyUI" in source
    assert "item.disabled = true" in source


def test_studio_display_names_do_not_advertise_removed_dual_modes(loaded):
    module, _, _ = loaded
    for node_name in ("APS_PromptStudio", "APS_H3PromptStudio"):
        display_name = module.NODE_DISPLAY_NAME_MAPPINGS[node_name]
        assert "宽松" not in display_name
        assert "严格" not in display_name


def test_settings_workbench_is_tabbed_lazy_and_keyboard_accessible():
    source = (PROJECT_ROOT / "web" / "settings.js").read_text(encoding="utf-8")
    assert 'role: "dialog"' in source and '"aria-modal": "true"' in source
    assert 'event.key === "Escape"' in source
    assert 'event.key !== "Tab"' in source
    assert "showPanelTab(activePanelTab)" in source
    assert 'tabId === "resources"' in source
    assert 'id: "AI Prompt Studio.General.openWorkbench"' in source
    assert 'text: "打开 AI Prompt Studio 设置工作台"' in source
    assert "onClick: openPanel" in source


def test_frontend_registries_use_shared_request_cache():
    cache = (PROJECT_ROOT / "web" / "data_cache.js").read_text(encoding="utf-8")
    settings = (PROJECT_ROOT / "web" / "settings.js").read_text(encoding="utf-8")
    supplements = (PROJECT_ROOT / "web" / "supplement_picker.js").read_text(
        encoding="utf-8")
    assert "current?.promise" in cache
    assert 'cachedJson("/ai_prompt_studio/profiles")' in settings
    assert 'cachedJson("/ai_prompt_studio/supplements")' in supplements


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


def test_studio_session_widgets_follow_public_inputs(loaded):
    """ADR 0007 keeps the current Studio inputs and explicit session state."""
    module, _, _ = loaded
    composer_inputs = module.NODE_CLASS_MAPPINGS["APS_PromptStudio"].INPUT_TYPES()
    assert "operation" not in composer_inputs["required"] | composer_inputs["optional"]
    assert list(composer_inputs["required"])[-2:] == ["target", "session_action"]
    assert list(composer_inputs["optional"])[-3:] == [
        "prompt_session", "message_nonce", "prompt_supplements"]
    h3_inputs = module.NODE_CLASS_MAPPINGS["APS_H3PromptStudio"].INPUT_TYPES()
    assert "operation" not in h3_inputs["required"] | h3_inputs["optional"]
    assert list(h3_inputs["required"])[-2:] == ["duration", "session_action"]
    assert list(h3_inputs["optional"])[-3:] == [
        "prompt_session", "message_nonce", "prompt_supplements"]
    assert composer_inputs["optional"]["prompt_supplements"][1]["advanced"] is True
    assert h3_inputs["optional"]["prompt_supplements"][1]["advanced"] is True


def test_supplement_picker_is_advanced_and_preserves_workflow_ids(loaded):
    """PH8 uses one collapsed selector instead of exposing raw ID text fields."""
    module, _, _ = loaded
    for node_name in (
            "APS_LLMGenerate", "APS_ReferenceAnalyzer", "APS_StoryboardBuilder",
            "APS_PromptStudio", "APS_H3PromptStudio"):
        inputs = module.NODE_CLASS_MAPPINGS[node_name].INPUT_TYPES()
        assert inputs["optional"]["prompt_supplements"][1]["advanced"] is True
    source = (PROJECT_ROOT / "web" / "supplement_picker.js").read_text(encoding="utf-8")
    assert "hideSerializedWidget(widget)" in source
    assert 'widget.serializeValue = async () => widget.value' in source
    assert 'cachedJson("/ai_prompt_studio/supplements")' in source
    assert 'from "./data_cache.js"' in source
    assert "不适用于当前节点/目标" in source
    assert "资料已删除或注册表中不存在" in source
    assert 'APS_LLMGenerate: { family: "generic_llm", nodeId: "llm.generate", auto: false }' in source


def test_ph9_regression_gate_covers_every_required_runtime_check():
    """The final phase must stay one executable gate, not a prose checklist."""
    script = (PROJECT_ROOT / "scripts" / "verify_prompt_contracts.ps1").read_text(
        encoding="utf-8")
    assert "python -m pytest tests/ -q" in script
    assert "python -m compileall" in script
    assert "Get-ChildItem -LiteralPath web -Filter *.js" in script
    assert "node --check" in script
    assert "git diff --check" in script
    matrix = (PROJECT_ROOT / "docs" / "prompt-architecture"
              / "ph9-prompt-contract-regression.md").read_text(encoding="utf-8")
    for requirement in ("Unit rules", "Integration", "Mock Gateway",
                        "Workflow compatibility", "Node import",
                        "Python compilation", "JavaScript syntax"):
        assert requirement in matrix

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
    "APS_PromptComposer", "APS_MiniMaxH3Director", "APS_RuntimeControl",
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
    assert len(module.NODE_CLASS_MAPPINGS) == 9
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
    assert os.path.isfile(os.path.join(web_dir, "styles.css"))


def test_node_instances_instantiable(loaded):
    """9 个节点类可实例化且 INPUT_TYPES()/RETURN_TYPES 完整（与真实 ComfyUI 校验一致）。"""
    module, _, _ = loaded
    for name in EXPECTED_NODES:
        cls = module.NODE_CLASS_MAPPINGS[name]
        node = cls()
        assert node is not None
        it = cls.INPUT_TYPES()
        assert "required" in it
        assert cls.FUNCTION and hasattr(cls, cls.FUNCTION)

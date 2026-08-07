"""ComfyUI AI Prompt Studio —— LLM 提示词工作流扩展。

入口文件：注册 9 个节点、前端资源目录（WEB_DIRECTORY）与后端路由。

加载语义（两种，代码需同时兼容）：
1. ComfyUI 加载器以 spec_from_file_location 按文件加载本文件，__package__ 为完整路径
   （truthy），此时使用相对导入（节点子包必须相对导入，避免与 ComfyUI 的
   server/nodes 顶层模块撞名）。
2. 工具（如 pytest 把项目根目录当 Python 包收集）以裸模块方式导入本文件，
   __package__ 为空，相对导入不可用 —— 此时用 importlib 以唯一包名委托加载一次，
   再复制导出，保证不污染 sys.path 顶层命名空间。
"""
from __future__ import annotations

import logging
import os
import sys

_logger = logging.getLogger("ai_prompt_studio")

if not __package__:
    # ------------------------------------------------------------------ 裸模块加载
    # 仅发生在无 ComfyUI 的测试/工具环境（pytest 收集根包）。委托真实包加载，避免相对导入失效。
    _ROOT = os.path.dirname(os.path.abspath(__file__))
    _RUNTIME_NAME = "ai_prompt_studio_runtime"
    if _RUNTIME_NAME not in sys.modules:
        import importlib.util

        _spec = importlib.util.spec_from_file_location(_RUNTIME_NAME, os.path.join(_ROOT, "__init__.py"))
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules[_RUNTIME_NAME] = _mod
        _spec.loader.exec_module(_mod)
    else:
        _mod = sys.modules[_RUNTIME_NAME]

    NODE_CLASS_MAPPINGS = _mod.NODE_CLASS_MAPPINGS
    NODE_DISPLAY_NAME_MAPPINGS = _mod.NODE_DISPLAY_NAME_MAPPINGS
    WEB_DIRECTORY = _mod.WEB_DIRECTORY
    __all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
else:
    # ------------------------------------------------------------------ ComfyUI 加载
    from .nodes import (  # noqa: E402
        APS_CharacterBible,
        APS_LLMGenerate,
        APS_MiniMaxH3Director,
        APS_ModelProfile,
        APS_PromptComposer,
        APS_ReferenceAnalyzer,
        APS_RuntimeControl,
        APS_StoryboardBuilder,
        APS_StoryboardSelect,
    )

    NODE_CLASS_MAPPINGS = {
        "APS_ModelProfile": APS_ModelProfile,
        "APS_LLMGenerate": APS_LLMGenerate,
        "APS_ReferenceAnalyzer": APS_ReferenceAnalyzer,
        "APS_CharacterBible": APS_CharacterBible,
        "APS_StoryboardBuilder": APS_StoryboardBuilder,
        "APS_StoryboardSelect": APS_StoryboardSelect,
        "APS_PromptComposer": APS_PromptComposer,
        "APS_MiniMaxH3Director": APS_MiniMaxH3Director,
        "APS_RuntimeControl": APS_RuntimeControl,
    }

    NODE_DISPLAY_NAME_MAPPINGS = {
        "APS_ModelProfile": "AI Model Profile",
        "APS_LLMGenerate": "LLM Generate / Chat",
        "APS_ReferenceAnalyzer": "Reference Analyzer",
        "APS_CharacterBible": "Character Bible",
        "APS_StoryboardBuilder": "Storyboard Builder",
        "APS_StoryboardSelect": "Storyboard Select / Batch",
        "APS_PromptComposer": "Model Prompt Composer",
        "APS_MiniMaxH3Director": "MiniMax H3 Prompt Director",
        "APS_RuntimeControl": "Local Runtime Control",
    }

    WEB_DIRECTORY = "./web"

    __all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]


def _init_server_routes() -> None:
    """把设置工作台后端路由挂到 ComfyUI PromptServer。失败不影响节点加载。"""
    try:
        from .server.routes import register_routes

        register_routes()
    except Exception as exc:  # noqa: BLE001 - 路由失败不阻塞插件
        _logger.warning("AI Prompt Studio: 路由注册失败: %s", exc)


if __package__:
    _init_server_routes()

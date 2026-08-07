# 兼容性说明 compatibility.md

目标环境：ComfyUI **v0.30.2**（已由本机源码确认），Python 3.13，Windows 11，torch 2.12.1+cu130。

## 使用的公开接口（不修改核心）

| 用途 | 接口 | 备注 |
|---|---|---|
| 节点注册 | `NODE_CLASS_MAPPINGS` / `NODE_DISPLAY_NAME_MAPPINGS` | V1 API，0.30.x 稳定 |
| 前端资源 | `WEB_DIRECTORY` → 挂载于 `/extensions/<pkg>/` | nodes.py 收集 |
| 后端路由 | `from server import PromptServer; PromptServer.instance.routes` | 自动注册 `/api` 前缀副本 |
| 前端扩展 | `app.registerExtension({name, setup, settings, nodes})` | comfyui_frontend_package 1.47.12 |
| 前端设置 | `app.extensionManager.setting.get/set(id, value)` | 服务端持久化到 comfy.settings.json（本插件密钥不用此机制） |
| 用户目录 | `folder_paths.user_directory` | 密钥/配置存放 |

## 已隔离的兼容风险

- **`comfy.logging` 已改名 `comfy.internal_logging`（0.30.0 破坏性变更）**：本插件不 import `comfy.logging`，日志用标准库 `logging`。
- 前端包版本：1.47.12。`app.registerExtension` 的 `settings`/`setup` 属性若在新版本变更，代码集中在 `web/settings.js` 一处适配。
- V3 schema（`comfy_entrypoint`）为可选迁移，本项目暂用 V1；如未来核心强制 V3，迁移点在 `__init__.py`。

## 第三方节点共存

- **MiniMax H3 三件套**（ComfyUI-MiniMax-H3-Turbo / DualClockSampler / TE-Speed-MiniMaxH3）已安装：H3 Director 输出 **STRING** 提示词，与核心 H3 节点 prompt 输入衔接，不重复采样后端。
- **ANIMA_BOOSTER 未安装**：只做存在性软检测（模块探测），无硬依赖；缺失时插件照常加载。
- 节点命名加 `APS_` 类名前缀、分类统一 `AI Prompt Studio`，避免与既有节点冲突。

## 无 GPU / 无 CUDA 环境

- 提示词相关功能（Gateway、Profile、Composer、H3 Director、Storyboard）只依赖 `requests`，**不依赖 torch/CUDA**，可在 CPU 环境加载与运行。
- 只有涉及图片输入（Reference Analyzer 的 IMAGE 输入）才需要 torch；图片编码路径在 torch 缺失时给出明确错误而非崩溃。

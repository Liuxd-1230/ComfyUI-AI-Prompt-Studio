# 决策记录 decisions.md

本文件记录所有自行选定的默认值与假设（规范 §3：不得因小问题停止开发；把假设记录在这里）。

## D1. 仓库与版本控制

- 仓库名 `ComfyUI-AI-Prompt-Studio`（沿用目录名），**公开**（用户指定：gh repo create 后已改为 public），owner `Liuxd-1230`。
- 公开仓库安全前提：密钥/本地配置/版权手册副本均被 .gitignore 排除，工作流 JSON 只存 profile_id，代码不含任何真实密钥。
- 分支 `master`（与全局 git 配置 `init.defaultbranch=master` 一致）。
- 每个 Phase 结束自动 commit + push。
- `docs/sources/*.html`（MiniMax 官方手册副本）**不提交**（版权边界，见 licenses-and-sources.md）。

## D2. 执行节奏

- 一口气完成 Phase 0–6；每阶段汇报（已完成/验证/问题/下一步）+ 提交推送；用户可随时打断。
- 验收 = 自动化验证（pytest 全绿 + 官方 H3 手册示例全过 + headless 冒烟）+ 可加载示例工作流；**不做真实 API Key 端到端**（用户访谈确认）。

## D3. API Key 与密钥安全

- 测试阶段用 mock 服务器；真实密钥由用户经设置面板填写。
- 密钥只存 `user/<pkg>/config.json`（ComfyUI user 目录）；前端只回脱敏值（`sk-***abcd`）；后端按 `profile_id` 解析密钥。
- 工作流 JSON 只保存 `profile_id`，绝不包含密钥；日志只输出脱敏值。

## D4. 冒烟测试

- 独立端口 + `--cpu` headless 启动用户 ComfyUI（Phase 1 末与 Phase 6 各一次），验证 `/object_info` 含 9 节点与设置路由，验完即关；不碰运行中的实例。
- **环境发现（2026-08-07，Phase 1 末）**：用户 ComfyUI 的 `standalone-env` 缺少 torch（`import torch` 失败，全盘 `E:\Comfy-Desktop` 下无 torch 目录，`manifest.json` 声明 torch 2.12.1+cu130 但未实际安装）→ ComfyUI 主进程无法启动，`/object_info` 冒烟不可执行。按安全边界（不安装 CUDA/Torch 大依赖）不代为安装。
- **替代冒烟（等价验证，已实现为 pytest 用例）**：
  1. `tests/test_smoke_loader.py`：逐行复刻用户 ComfyUI 0.30.x `nodes.py::load_custom_node` 的加载语义（目录节点 `sys_module_name = module_path.replace(".", "_x_")` + `spec_from_file_location(./__init__.py)` + `sys.modules` 注册 + `exec_module` + `WEB_DIRECTORY` 目录存在 + V1 `NODE_CLASS_MAPPINGS` 注册 + `RELATIVE_PYTHON_MODULE` 赋值），验证扩展在其语义下可加载、9 节点完整。
  2. `tests/test_smoke_routes.py`：伪造 `server.PromptServer.instance.routes`（与用户 ComfyUI 一致的 `web.RouteTableDef()`），用真实 aiohttp 起临时 HTTP 服务做端到端往返（状态/档案 CRUD/密钥隔离/404/400/设置），验证全部 15 条路由注册与处理器接线。
- 结论：本扩展不依赖 ComfyUI 启动即可完整加载与验证；真实启动冒烟保留到用户补齐 torch 后（Phase 6 视环境情况执行或沿用替代冒烟）。

## D5. Schema 用 dataclass 而非 pydantic

- 理由：venv（3.13.12）与测试环境（系统 3.13.11）保持零第三方依赖一致；pydantic v2 虽在 venv 可用但测试环境未装。
- 所有 Schema：dataclass + `schema_version` + `migrations` 注册表（`upgrade(data)->data`）+ `to_json`/`from_json`（输入容错：忽略未知键、缺失键取默认）。

## D6. HTTP 层

- `requests` 同步 + SSE 流式解析；节点在 ComfyUI 工作线程内执行；取消通过共享 `stop_event` + 轮询检查。
- 超时/重试策略：连接超时 10s、读超时可配置（默认 120s）；幂等 GET/探测可重试 1 次，POST 生成不自动重试（防重复扣费）。
- 错误按 HTTP 状态码归一化；`error.code` 视为可选。
- reasoning 参数：Responses 用 `reasoning.effort`（off 不发该字段）；Chat Completions 用 `reasoning_effort`，**仅当 provider=deepseek 时发送**（通用 OpenAI 兼容端点对未知参数可能 400）。同理 `response_format`(json) 仅 deepseek 发送。
- usage 命名差异：Responses `input/output_tokens`，Chat `prompt/completion_tokens`，adapter 统一映射为 LLMResult.usage（`accumulate_usage`）。

## D7. 联网搜索范围（v1）

- 只做 DeepSeek Responses 原生 `web_search` 工具 + 离线降级（带明确警告）；外部搜索后端留可插拔接口（services/search.py），不强制第三方 Key。
- 降级链：Responses 原生 → Responses function tool → Chat function tool → 外部后端 → 离线+警告。
- 401/402/403/429/5xx/网络失败**不静默降级**；只有「接口/参数不支持」触发协议降级。

## D8. 视觉模型

- 档案支持通用 OpenAI 兼容视觉端点（`vision_base_url` + `vision_model`），图片 base64 data URL 编码调用（用户访谈确认）。
- DeepSeek v4-flash 探测 vision=false；未配置视觉端点时 Reference Analyzer 明确报错，不伪装。

## D9. 设置工作台形态

- ComfyUI **内嵌面板**（菜单按钮打开模态面板，vanilla JS 零构建），中文+英文双语、tooltip、密钥脱敏、API 测试、能力状态、runtime 状态、H3/ANIMA prompt 预览、验证报告、Character Bible JSON 预览、冲突与不确定字段显示（用户访谈确认）。

## D10. ANIMA 档案

- 按官方 Civitai 卡片实现三套档案：Base（官方前缀+负面+score）、Aesthetic（去 score 标签）、Turbo（官方示例前缀 + CFG 1 / 8-12 步 GenerationProfile）。
- ANIMA_BOOSTER 仅软检测（存在性提示），不硬依赖、不复制其实现。

## D11. H3 渲染管线

- LLM 生成结构化 H3 plan → JSON Schema 校验 → Python 确定性渲染（首行指令、三字段/六段、标签）→ 规则验证 → 可选一次模型修复。
- 不重复实现 ComfyUI 原生 H3 采样后端；输出 STRING 与核心 H3 节点衔接（已确认其 prompt 输入为 STRING）。

## D12. 前端

- 零构建 vanilla JS + CSS；不引入 npm 依赖；`node --check` 验证语法。

## D13. 本地运行时

- 三个后端全部实现（Ollama/llama.cpp/LM Studio v1），以 mock server 测试；真实服务检测为机会式（运行中则做一次只读探测）。
- 第一版不把 Transformers 模型加载进 ComfyUI Python 进程。

## D14. 依赖

- 仅 `requests`（venv 已有）；不安装 CUDA/Torch 大依赖；测试用系统 Python 3.13.11 的 pytest 9.1.1。

## D15. H3 渲染/校验细节（Phase 5）

- **镜头检查只扫描描述字段/段**：`SHOT_RE` 会误匹配首行对齐指令里的 `(from [Shot 1])` 与 retention_analysis 段的 `[Shot N]` 引用，因此 `_check_shots` 只在 `integrated_multimodal_description`（四模式）或 `detailed_description`（R2V）内找镜头。
- **畸形时间戳独立检测**：`SHOT_RE` 只捕获合法 `MM:SS.mmm`，格式错误的 `At XX:XX:XXX` 会被当成「缺失时间戳」；新增 `AT_RE` 单独捕获并报 `h3_ts_format`。
- **`<d>` 语言标注独立检测**：`DIALOGUE_RE` 需要 `[Language]` 才匹配，缺失语言标注的对白匹配不上；改为对每个 `<d>` 直接检查其后是否紧跟 `[`。
- **H3 修复不引入第二套 skill 系统**：repair 操作把校验问题经 `build_plan_prompt(repair_issues=...)` 回灌给 LLM，一次修复后重新渲染+校验；与 Composer 的 YAML skill 系统（面向图像 prompt）职责分离，不建 `skills/minimax_h3/`。
- **convert_storyboard 回退链**：LLM 计划解析失败或空镜头时，回退为 `convert_storyboard` 的结构映射（镜头时间分布、说话人 S1..、manifest→subjects/assets/retention），描述沿用分镜文本并记 warning。
- **图片映射**：`map_image_assets` 按模式把输入图映射为 Picture 资产——I2VA 首帧（0.00s）、FL2VA 首尾（0.00s / 有效时长）、L2VA 尾帧（有效时长）；已存在的标签跳过不重复。

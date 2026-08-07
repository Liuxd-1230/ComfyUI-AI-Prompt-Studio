# 决策记录 decisions.md

本文件记录所有自行选定的默认值与假设（规范 §3：不得因小问题停止开发；把假设记录在这里）。

## D1. 仓库与版本控制

- 仓库名 `ComfyUI-AI-Prompt-Studio`（沿用目录名），**私有**（gh repo create --private），owner `Liuxd-1230`。
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

## D5. Schema 用 dataclass 而非 pydantic

- 理由：venv（3.13.12）与测试环境（系统 3.13.11）保持零第三方依赖一致；pydantic v2 虽在 venv 可用但测试环境未装。
- 所有 Schema：dataclass + `schema_version` + `migrations` 注册表（`upgrade(data)->data`）+ `to_json`/`from_json`（输入容错：忽略未知键、缺失键取默认）。

## D6. HTTP 层

- `requests` 同步 + SSE 流式解析；节点在 ComfyUI 工作线程内执行；取消通过共享 `stop_event` + 轮询检查。
- 超时/重试策略：连接超时 10s、读超时可配置（默认 120s）；幂等 GET/探测可重试 1 次，POST 生成不自动重试（防重复扣费）。
- 错误按 HTTP 状态码归一化；`error.code` 视为可选。

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

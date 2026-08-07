# Changelog

本项目按阶段（Phase 0-6）迭代，每阶段完成即提交并推送（master）。

## [0.2.0] - 2026-08-07 — P0/P1 集成修复轮

### Batch E — 集成收尾

- 依赖修正：`requirements.txt` / `pyproject.toml` 补 PyYAML 硬依赖，vision 可选依赖（Pillow/numpy）单列。
- 真实 ComfyUI 冒烟（`--cpu` headless，独立端口）：9 节点注册、`/object_info`、设置路由、档案 CRUD、密钥不落盘（config.json 无 api_key/api_key_ref）、`/skills`、`/runtime`、示例工作流节点类型与无密钥校验、扩展静态资源 `/extensions/ComfyUI-AI-Prompt-Studio/*` 全部 200、`/api` 前缀路由、无扩展加载错误、验后关闭并释放端口。
- 文档：`docs/research.md` §7 补充、`docs/known-limitations.md` 新建、`docs/decisions.md` D22-D23。

### Batch D — 数据链完善

- 多图身份判断：`identity_agreement` / `cluster_by_identity` / `judge_identity` / `identity_consensus`（多主体只合并最高一致度分组，防跨主体串绑；`__subject_identity__` 冲突）。
- 视觉/文本 Profile 解耦：`AIProfile.vision_profile_id`（视觉分析可指向另一档案，含其配置与密钥）。
- Storyboard 消费 Manifest：character 类 Subject 补成角色表并沿用真实 subject_id；已有 CharacterBook 时不重复注入。
- Prompt Skill 管理：内置只读 + 自定义可管理（复制/新建/改/删/启停/校验/hash），`/skills` 6 路由 + 设置面板 Skill 区。

### Batch C — 运行时与工具链

- `/runtime` 与 Runtime Control 节点共用 `run_runtime_action` 服务层（P0）。
- 真实自定义运行时后端（status 走 `/v1/models`，load/unload 走 `/models/{load,unload}`）。
- 外部搜索后端（`search_url`）降级注入；函数工具循环（`MAX_TOOL_ROUNDS=4`，now/search）；本地运行时 `unload_policy`（after_request / after_success）。

### Batch B — API 与 UX

- 用户 `system_prompt` 作为真实 system 指令（内部守则层优先 + 不静默丢弃）。
- 采样参数（temperature/top_p/frequency_penalty/presence_penalty/max_tokens）移出节点 UI，进档案高级设置（None=不发送）。
- API 附件（ATTACHMENT/ATTACHMENT_LIST）：Responses/Chat 官方结构映射、能力门槛、路径安全与大小限制。
- 结构化输出：gateway `output_schema`（能力允许→协议层 schema；DeepSeek→提示词约束+解析校验）。

### Batch A2 — Prompt Audit

- 全量提示词审计 + 参考项目调研（PromptForge / Prompt Assistant / TE_MAN / DaSiWa / MiniMax 官方手册）→ `docs/prompt-comparison.md` + `docs/prompt-audit.md`。
- Reference Analyzer / H3 / Storyboard / 技能提示词重写；注入守则（数据即数据）；4 个回归用例 + 语义契约测试。

### Batch A — 正确性修复

- ANIMA 默认 natural_language + 结构化 AnimaPromptPlan（Hybrid 去重）；CharacterBook 真正接通 + Speaker ID 唯一分配。
- H3 媒体独立编号、R2V 英文（一次修复、绝不假翻译）、模式资产约束；DeepSeek 按具体模型能力探测。
- llama.cpp load/unload body 修正（`{"model": ...}`）。

## [0.1.0] - 2026-08-07

### Phase 6 — 文档与发布

- 中文 README 补齐：安装 / 快速开始 / 9 节点说明 / ANIMA 与 H3 官方档案 / 安全模型 / 兼容性 / 后端路由 / 测试。
- 示例工作流（`examples/`）：`h3_full_chain.json`（H3 全链路）、`anima_full_chain.json`（ANIMA 全链路），均不含密钥；新增自动化验证（节点注册 / 连线一致 / 无密钥）。
- CHANGELOG 建立。

### Phase 5 — MiniMax H3 Prompt Director

- 五模式确定性渲染器 `renderers/minimax_h3.py`：T2VA/I2VA/FL2VA/L2VA 三字段（含首行对齐指令，FL2VA 两位小数、默认单镜头路径）、R2V 六段；`[Shot 1]` 无时间戳、后续 `[Shot N] At MM:SS.mmm` 严格递增；对白 `<d>[Language] ...</d>` 原语言保留；retention 标记；说话人 ID。
- 校验器 `validators/minimax_h3.py`：结构错误（段顺序、镜头编号/时间戳/格式/递增、标签编号、指令句式、对白配对与语言标注）+ 内容警告（soundscape 不重复对白、配乐禁抽象情绪词、R2V 风格开场/retention/summary 前缀）；镜头检查只在描述段内进行，避免误匹配指令行与 retention 引用。
- 计划服务 `services/h3_plan.py`：LLM 指令构造、JSON 容错解析（Shot 1 强制无时间戳、后续时间戳强制严格递增）、分镜 → 计划结构转换、图片 → Picture 资产映射。
- 节点 `APS_MiniMaxH3Director`：generate / rewrite / convert_storyboard（LLM 失败回退结构映射）/ audit（不调模型）/ repair（校验问题回灌 LLM）；输出 STRING 直连核心 H3 节点。
- 新增测试 72 个（渲染 / 校验 / 计划 / 节点），决策 D15。

### Phase 4 — Storyboard 与 ANIMA

- Storyboard Builder（LLM 拆分场景/镜头/节拍、模型无关 JSON 解析、连续性报告）。
- Storyboard Select / Batch（场景 / 镜头 / 区间 / 全部，不调模型）。
- Prompt Skill 系统（内置 YAML、id/version/target/renderer/system_prompt/validators/source/hash）。
- Model Prompt Composer（7 操作 × 7 目标、正负拆分、PROMPT_PLAN / GENERATION_PROFILE、audit/repair）。
- ANIMA renderer + validator（官方前缀/负面、Base/Aesthetic/Turbo 档案、标签分段排序、`@artist`、LoRA 触发词、safe/sensitive）。

### Phase 3 — Reference 与 Character

- vision 服务（base64 data URL、OpenAI 兼容视觉端点、批次）。
- Reference Analyzer（11 模式、多图逐图 → 共识/冲突、text_priority 合并、REFERENCE_MANIFEST、IMAGE 透传）。
- Character Bible（5 合并策略、字段锁定、conflict report、说话人 ID）。
- 测试 34 个新增。

### Phase 2 — Gateway 与本地运行时

- 统一 LLM Gateway：Responses / Chat Completions 双 adapter（SSE、reasoning、tools、citations、usage、错误归一化）。
- 能力探测（`/models` + 缓存 + 手动重跑）；联网搜索降级链（原生 → 离线+警告；认证/余额/限流/5xx 不降级）。
- LLM Generate / Chat 节点功能化；Local Runtime Control + Ollama / llama.cpp / LM Studio 三后端。
- 测试 51 个新增。

### Phase 1 — 最小可运行骨架

- 13 个 Schema（dataclass + 迁移 + 容错 JSON）。
- 配置存储（密钥脱敏、`api_key_ref` 剥离、用户目录持久化）+ 后端路由。
- 9 个 APS 节点全部注册；AI Model Profile 功能化；内嵌设置面板（vanilla JS）。
- 冒烟：ComfyUI 加载器语义复现 + 真实 aiohttp `RouteTableDef` 路由回环。
- 测试 62 个（含安全：密钥不进工作流 JSON / 日志脱敏）。

### Phase 0 — 调研与骨架

- 调研文档 `docs/research.md`（ComfyUI 0.30.2 接口、DeepSeek API、ANIMA 官方档案、本地运行时、H3 官方手册）。
- 决策记录 `docs/decisions.md`（D1-D14）、ADR-0001~0004、许可与来源边界、兼容性说明。
- 目录骨架、LICENSE（MIT）、pyproject、.gitignore；公开仓库建立（Liuxd-1230/ComfyUI-AI-Prompt-Studio）。

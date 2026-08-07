# Changelog

本项目按阶段（Phase 0-6）迭代，每阶段完成即提交并推送（master）。

## [0.2.1c] - 2026-08-07 — 前端入口修复（原生 Settings）

- **最终入口**：按产品决定不占用 Sidebar，也不注入 `.comfy-menu`；入口放入 ComfyUI 原生 Settings 的 `AI Prompt Studio > General > Settings Workbench`。
- **动作兼容**：官方 Settings API 没有 button/action 类型，因此使用一次性 combo：选择 `Open Settings Workbench` → 调用现有 `openPanel()` 打开大型设置工作台 → 自动复位为 `idle`。
- **原生设置**：`AI Prompt Studio.General.language`（zh/en）与 `AI Prompt Studio.General.openWorkbench`；API Key 不进前端设置，仍只存服务端 SecretStore。
- **去重与诊断**：`openPanel()` 复用 `#aps-overlay`；加载/Settings 注册/复位失败都有 `[AI Prompt Studio]` 状态日志，不输出密钥、提示词或附件内容。
- **测试**：`node --check web/settings.js`、pytest smoke 资源检查与全量 pytest；生产 `settings.js` 不依赖 Sidebar/legacy 入口模块。

## [0.2.1b] - 2026-08-07 — 收尾补丁（默认路径 Natural / VLM 否决 / 按需 Key / metadata）

- **Generic/SDXL/FLUX Natural 模式消费 CharacterBook（默认路径修复）**：`render_generic` natural_language 分支此前直接返回 `text.strip()`，把整理好的全部人物特征丢弃；而 Composer 默认 `prompt_mode=natural_language`。现改为 `_natural_with_characters()`——每人物一句 `A, with black short hair and a white military uniform.`，正文已含特征跳过（防重复），无人物时行为不变。
- **VLM same=false 真正否决全量合并**：`identity_consensus_with_verdict` false 分支在字符串一致度把候选全聚成一组时，不再 `consensus_of(全部)`（那会把不同主体的 traits 真的合起来）——只取置信度最高的一张作主人物，其余保留为 `__subject_identity__` 冲突。
- **Reference Analyzer 按需取 API Key**：有 text_anchor → 要求文本档案 Key；有 images → 要求视觉档案 Key（vision_profile_id 解耦）。只做图片分析时**不再**要求文本档案配置 Key（Text Provider ≠ Vision Provider）。
- **PromptPlan.character_bindings 全量**：CharacterBook 场景记录全部人物（此前只记 first_bible）。
- **文案清理**：Reference Analyzer DESCRIPTION 去掉「/视频」。
- 测试：main-flows Flow 4/5/6 参数化 prompt_mode（tags + natural，断言 natural 消费 book + bindings 全量）；新增「VLM 不同主体单簇否决合并」「图片-only 无文本 Key」「有锚点必须文本 Key」；全量 443 passed。
- 文档：research.md §8.8、decisions.md D26、known-limitations.md。

## [0.2.1a] - 2026-08-07 — 小补丁（LM Studio 字段 / VLM 权威 / 多人物 / 附件 / 降级）

- **LM Studio v1 模型字段修正（P0）**：官方 `GET /api/v1/models` 的模型标识是 **`key`**（`id` 只存在于 `loaded_instances` 实例条目；v0 才是 `data`+`id`）。此前实现与测试都用 `id` 匹配模型（mock 与代码同错）→ 独立执行 unload 时按 `loaded_instances` 反查 instance_id 找不到。现解析 `m.get("key") or m.get("id")` 兼容两代，测试改用官方真实结构；新增「模型 key 未找到 → 可读错误且不发卸载请求」用例。
- **VLM 多图身份判断接管 merge（P1）**：新增 `identity_consensus_with_verdict`——VLM same_subject=True 直接合并全部候选（VLM confidence 写入），False 禁止全量合并（主主体 + `__subject_identity__` 冲突，防串绑），VLM 失败才回退字符串一致度启发式；旧字符串算法不再覆盖 VLM 结论。
- **Generic/SDXL/FLUX 消费完整 CharacterBook（P1）**：render_generic 新增 `book` 参数，多人物特征全部进最终 prompt（此前只取 first_bible，第二个人物可能丢失）；Composer 确定性/LLM 路径均传 book；主链路测试改为 text 只写剧情、特征全部来自 CharacterBook。
- **Responses adapter 补 `import json`**：兼容端点 function_call arguments 为 dict 时不再 NameError。
- **附件两处修正**：`_document_extractable` 扩展名比较改为无点小写（pdf/docx）；`local_extract_document` 按 UTF-8 **字节**截断并回退到有效字符边界（中文长文档不再超 512 KB）。
- **Gateway 降级重算 Structured Output**：ProtocolUnsupported 降级到另一协议时按新协议重新计算结构化输出策略（deepseek-v4-flash Responses→Chat fallback 不再把 json_schema 发给 Chat）；约束注入幂等。
- 文档：research.md §8.7（含官方来源）、decisions.md D25、known-limitations.md（key 字段 / VLM 权威 / 字节截断）、README 兼容性节、CHANGELOG。

## [0.2.1] - 2026-08-07 — 加固轮（无新功能、无架构重构）

### P0 修复（运行时 / 协议 / 数据）

- **Composer 崩溃修复**：`nodes/prompt_composer.py` `compose()` 以 `book_context` 调用 `_generic()` 而函数无此参数且内部引用未定义 `book_context` → generic_image / sdxl / flux_kontext 崩溃（TypeError/NameError）。已加参数并接线，不依赖 TypeError 兜底。
- **API Key 解耦**：Composer audit / convert / generate+tags 与 H3 audit 完全离线（不查密钥）；H3 `convert_storyboard` 无 Key 时走确定性分镜转换（带警告「无 API Key：已使用确定性分镜转换」），有 Key 才 LLM 增强。只有 LLM 路径（expand/rewrite/translate/repair、ANIMA natural/hybrid generate、自定义技能 LLM）要求密钥。
- **DeepSeek 结构化输出按协议分能力**：官方文档核实 `deepseek-v4-flash` 支持 Responses API + `text.format` json_schema（`structured_output_responses=True`）；Chat Completions 无 json_schema（`structured_output_chat=False`）。Gateway 按当前协议判定：Responses 走 `{"text":{"format":{"type":"json_schema",...}}}`，Chat 降级提示词约束 + JSON 解析 + 校验。
- **附件警告上节点输出**：`load_path_attachments()` 的 `file_warnings`（路径越界、文件缺失、超限、跳过）合并进 LLM Generate 最终 `warnings` 输出，不再丢失。
- **PDF/DOCX 本地文本提取（方案 A）**：pypdf / python-docx 惰性导入；无原生文件输入支持的 Provider 降级为本地提取文本 + 警告「Provider 不支持原生文件输入，已本地提取文本发送」；扫描件/无文本层明确报错；非 PDF/DOCX 二进制明确报错（提示 supports_files）。PPTX/XLSX 明确不在支持范围。
- **DeepSeek 附件能力诚实化**：`deepseek-v4-flash` vision=False / files=False（官方文档确认 image/file 输入不支持，`input_image` 仅占位）；能力门槛阻止发送。
- **Responses 工具调用 call_id 修正**：`ToolCall(id=<模型返回的实际 call_id>)`；`function_call_output` 与模型返回的 call_id 一致，绝不伪造 `call_0`；覆盖流式 function_call、非流式 output_item.done、多工具调用（按 item_id 关联，call_id 取自 function_call item）。
- **LM Studio v1 探测顺序**：`GET /api/v1/models` 优先 → v0 降级 → 都失败 = 不可用；unload 用官方 `{"instance_id": ...}` 而非 `{"model": ...}`；运行时状态保存 model id + instance id；load 后记录 instance_id，unload 优先用已存实例，用户只给 model 时查已加载实例列表。

### Prompt 修复（数据污染 / 规范）

- **Reference Analyzer H3 提示词**：删除相机运动/时间运动/视频运动/运动序列（静态图；相机运动归 H3 Director）。
- **类别语义修正（防污染 Character Bible）**：scene/composition/object → `current`，style → `variable`（不再使用 `stable`）。
- **ANIMA natural 提示词**：官方前缀 `masterpiece, best quality, score_7, `（不再强制 `safe`，Aesthetic 无 score）；Natural 与 Character Bible 短语边界去重（「long black hair」vs「her long black hair」）；多人物属性绑定保持（A/B 各自特征不串位）。
- **分镜人物 ID**：沿用已有 character_id（char_01/char_02），绝不臆造 c1/c2；JSON 示例改为 `"characters": ["char_01", "char_02"]`；仅真正新人物才新建 ID。
- **批量身份判断 `batch_identity_check`**：多图 → 一次 VLM「是否同一视觉主体」裁决（same_subject+confidence+evidence）→ 逐图分析 → 特征共识；最多 6 张代表图；VLM 失败回退确定性启发式。
- **身份提示词只比较可观察身份特征**（面部比例、发际线、眼型、鼻/嘴几何、明显标记、稳定身体比例）；服装/背景/姿势仅弱辅助。
- **H3 retention 标记按官方手册核实**：audio 集合含 `weak_reference`；校验器按资产类型检查（visual: fully_preserved/partially_preserved/attribute_transfer/weak_reference；audio: fully_copy/partially_copy/reference/weak_reference）。
- **ANIMA Safety 标签产品决策（补充 P0）**：`content_tier` → `safety_tag`（none/safe/sensitive/nsfw/explicit，**默认 none**）；Composer 只在用户明确选择时注入，不做内容审查（模型认为敏感→自动改 safe 禁止）；三模式（tags/natural/hybrid）一致；用户节点 `safety_tag` > Prompt Plan 建议 > 无标签（用户选 none 时 Plan 的 safe 也不注入）；旧 content_tier 迁移；技能 YAML 去除硬编码 safe；校验器只查格式（最多一个、位置正确），nsfw/explicit 非语法错误。

### 结构化输出（P1）

- H3 Prompt Director（初始 + 修复）与 Storyboard Builder 原生 structured output：`H3_SCHEMA` / `STORYBOARD_SCHEMA` JSON Schema；Provider 支持原生 → 协议层 Schema，否则保留 JSON 模板。

### 新增回归测试

- `tests/test_main_flows.py`：8 条主链路（普通 LLM、单人物、多人物、generic_image、SDXL、FLUX、H3、离线审计）。
- 附件：本地提取 PDF/DOCX、扫描件报错、非文档报错、降级文本+警告、二进制报错、警告达节点输出。
- LM Studio：v1 优先、unload 用 instance_id、回退已加载实例列表。
- Adapters：Responses call_id（流式/非流式/多工具）。
- Gateway：按协议结构化输出（Responses schema / Chat 降级 / 能力门）。
- ANIMA：safety_tag none/safe/sensitive/nsfw/explicit 五态、natural/hybrid/tags 三模式 none、content_tier 迁移。
- ANIMA natural：短语边界去重、多人物绑定保持。
- Reference：VLM 批量身份裁决 + 回退启发式。

### 文档

- `docs/research.md` §8（DeepSeek 结构化输出/附件/call_id、LM Studio、ANIMA safety、H3 retention，含官方来源与日期）；`docs/decisions.md` D24；`docs/known-limitations.md`、`docs/prompt-audit.md` 0.2.1 节。
- README（ANIMA safety_tag、可选 doc-extract 依赖）；pyproject/requirements 版本 0.2.1 + doc-extract 可选依赖。

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

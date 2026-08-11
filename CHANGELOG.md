# Changelog

- P4.1 容错与可诊断性：H3 CREATE 结构化 Plan 与 Studio REFINE ChangeSet 遇到非 JSON/畸形协议结果时最多非破坏性重试一次；首次失败的校验问题与截断 raw 作为不可信任务数据反馈，第二次仍失败则在 backend warning 和用户错误中保留有界 raw 摘要，稳定 Session/revision 不变。ChangeSet/语义错误去重限长；指纹错误只提示当前真实可用的新会话/历史恢复操作；没有两个成功版本时，工作台不再 Queue 一个必然失败的恢复请求。
- Persistent P4 Session/Revision 返工：`PromptSession` 升级为可迁移的 v2 envelope；不可变 revision 保存稳定 ID、parent/base revision、消息 ID、变更/依赖/失效路径、renderer signature，以及实际 Model Core、Skill、来源对象和 H3 媒体内容哈希。恢复旧版不再 `pop()` 历史，而是创建指向旧 revision 的新版本；历史和聊天分别有明确上限。Composer/H3 新增追加式 `message_nonce`；bound Session 每次 Queue 都先比较权威上下文，再让相同/空消息走零 LLM、零 revision 路径。旧 v1 workflow Session 保留当前结果与历史并进入显式 `legacy_unbound` 状态，新修改需新建会话；旧 widget 顺序保持不变，`continue_previous` 不再拥有重置语义。“新会话”按钮只标记动作，旧 Session 会保留到新 CREATE 成功提交。
- Persistent P3 返工：语义一致性不再是孤立库与 mock-only 测试。Prompt Composer 和 MiniMax H3 Director 的 CREATE 会执行确定性语义校验；REFINE 在事务候选上按风险分级，只有动作/状态/时间线/身份/参考/重大构图/广义负向及无法证明兼容的风格修改才调用真实 Gateway Semantic Critic。Critic 仅接收受影响字段的 before/after、相邻镜头/图像依赖、ChangeSet 与锁定值，不接收完整 Plan/聊天历史，也无修改权。不可修复错误原子失败；可修复错误最多生成一次 issue 路径限定的新 ChangeSet，并重新经过授权、Diff Guard、语义/高风险 Critic/协议校验后才提交。Character Bible 锁定特征及 H3 speaker/reference 身份绑定使用稳定事实锁，每轮解析当前索引并复核其值，避免列表增删造成锁漂移；生产测试覆盖 Critic 拒绝、无关修复拦截、单次修复和失败不 commit。
- Persistent P2 事务返工：Composer 与 H3 Director 的生产 REFINE 已从根对象 Plan Patch 迁移到 reasoned `ChangeSet`；每次修改包含 revision、plan type、请求/依赖变更、失效事实、约束冲突和 reason。提案后会再做一次独立的紧凑结构化 intent/impact 审批，未批准的直接或依赖路径不得进入授权集。新主链实行 clone-first Impact Analysis、intent scope/路径/索引/值类型/锁/不可变元数据校验、提案与 normalizer 分段 Diff Guard、用户文本独立授权的 broad rewrite、最多一次定向修复和带 revision CAS 的 Session 整体原子交换。图像事务把 positive content 与 negative 放入同一影响图并对最终候选做冲突校验；H3 把 duration、manifest、媒体编号和 Session locks 纳入事务，拦截未闭合的时长/镜头切点失效。旧 Patch API 仅保留为非节点兼容入口。
- Persistent P1 返工：ANIMA Plan Normal Form 升级到 v2，移除可编辑的 `natural_body`、人物 `description` 与平行 tag 缓存双真源；Natural/Tags/Hybrid 统一从正式 Plan 派生，负向约束进入最终 negative。新增显式 v1→v2 迁移（歧义旧 prose 安全拒绝且不改 revision）、统一字段矩阵的确定性所有权校验、生产 Session 使用的 `PlanAdapter.to_llm_context()`，并把四个 ANIMA 结构化 Skill、renderer、Prompt Composer CREATE/REFINE 及 workflow Session 统一到 v2。
- 架构升级：Prompt Composer 与 MiniMax H3 Director 增加 workflow 持久化 `PromptSession`，自动 CREATE/REFINE、受限 Plan Patch、Current Prompt 与聊天摘要；后续 P4 已将破坏性回退迁移为不可变 revision restore。
- 增强 `APS_LLMGenerate` 默认 system prompt：强调准确遵循指令、合理利用上下文、在歧义时推断意图，并优先返回简洁可用的结果。
- 修复 `APS_UnloadModel` 重复卸载已释放模型时报错：已卸载现在作为成功的幂等结果放行；错误模型 key 与服务故障仍会明确阻断。

本项目按阶段（Phase 0-6）迭代，每阶段完成即提交并推送（master）。

## [Unreleased] — Z-Image / Qwen Edit 与图片引用

- 修复设置工作台把 `disabled: false`/`checked: false` 错写成仍然生效的 HTML 布尔属性：已有档案现在可以真正点击“保存密钥”，未勾选能力也不会被误显示为勾选；密钥区新增明确的已保存/未保存状态与脱敏值。
- 本地 OpenAI 兼容地址若在根路径返回 HTTP 200 错误 JSON，探测器会显示真实错误，并实测 `/v1`；仅当 `/v1` 真正生成文本时才自动保存正确根地址。Reference Analyzer 的关联视觉档案统一使用目标档案主 endpoint/model/key，洋红测试图的目的和结果会明确显示。
- Storyboard Select 的场景/镜头选择不再要求猜测 LLM 生成的内部 ID：支持 `1`、`scene_01`/`shot_01`、中文标签和真实 ID，失败时列出全部可选值。SSE 解析器兼容 LM Studio 中文 JSON 流中的未转义换行续行，并强制按 UTF-8 解码，避免静默丢事件或中文乱码。
- ANIMA 的 expand/rewrite/repair 内置 Skill 明确要求所有视觉描述字段输出英文；中文输入须保真翻译，只有角色名、专有名词和画面内文字允许保留原语言。
- 全仓整改：修复节点档案覆盖丢失、高级采样参数未发送、会话 replace 假替换、context 重复、失败路径不卸载、运行时断线假成功、同步 HTTP 阻塞 Comfy 事件循环及外部数据提示注入。
- Reference Analyzer 不再把多主体图片重新绑定给主人物；图片引用按实际使用和连接顺序编号；Storyboard 增加真实 Comfy 列表输出并强制场景数/总时长契约；人物 ID 改为唯一句柄。
- H3 对齐官方 Skill：4–15 秒、Ref2VA 图片/视频/音频入口和边界、镜头同步声、引用/说话人定义、闭唇/转场/截断/画面文字、严格 JSON Schema、350–500 词密度提示，以及节点内导演工作台。
- Prompt Skill 支持递归加载、停用生效、来源/完整内容 hash、按自身 family/renderer 分派；设置页可查看、新建、编辑并显示加载错误。
- LM Studio 支持 `LM_STUDIO_API_TOKEN`，同一模型多个 loaded instance 会全部卸载；卸载节点兼容独立输出节点和提示词透传两种用法。
- Composer 新增 `z_image_turbo` 和 `qwen_image_edit_2511`：前者采用长自然语言、9 步、CFG 0、空负面；后者使用直接编辑指令和 `Figure N` 多图引用。SDXL/FLUX 仅保留旧工作流兼容。
- 新增 `APS_ReferencePrompt`：给 `image_1`～`image_3` 接图后，在提示词输入框键入 `@` 选择带缩略图的引用；可输出 Qwen `Figure N`、H3 `<Picture N>` 与 `REFERENCE_MANIFEST`。
- 新增两个内置 Prompt Skill、11 个节点的中文 Markdown 帮助，以及仅连接本扩展节点的 `examples/aps_usage_showcase.json`。
- 测试新增专用渲染、图片引用、档案覆盖、跨主体绑定、H3 引用、运行时与示例接口契约；全量 514 项通过，并在 ComfyUI 0.31.1 隔离端口完成 11 节点注册及重复卸载调度验证。
- H3 Director 遇到第三方端点忽略 JSON Schema、返回普通文本时，不再让工作流崩溃：保留模型原文并回退为可编辑的单镜头计划；第三方 DeepSeek 代理也不再继承官方端点的结构化输出能力。
- Storyboard 与 H3 共用递归 strict JSON Schema 规范化，所有嵌套对象自动补齐完整 `required` 与 `additionalProperties: false`，修复严格端点的 HTTP 400。
- Storyboard Builder 遇到兼容端点返回非 JSON 时，不再崩溃或重复调用 API；保留用户原始故事并回退为可编辑单镜头，在 continuity 中明确记录 warning。
- 档案与能力检测整改：Profile/模型改为动态可选下拉；模型目录兼容 `data`/`models`/数组结构；档案或密钥变更及探测失败会清除旧能力；`/models` 不再被误当成协议/结构化输出证明；主模型视觉与独立视觉服务分开记录。Z-Image/Qwen/Generic 遇到第三方模型返回普通文本时保留原文，不再因缺少 `positive` JSON 崩溃。
- 能力探测改为真实执行矩阵：以 Gateway 实际请求格式分别调用 Chat、Responses、JSON Schema/JSON Object、函数工具、视觉、文件与原生联网；HTTP 200 但内容不符合探针也判失败。设置页以勾选状态和逐项 HTTP 诊断展示结果，视觉/文件实测失败会同步关闭档案开关；附件与工具请求按已通过的协议自动选路。
- 新增完整中文节点端口参考和模式提示词示例，并扩写 11 个节点内嵌帮助页；测试自动核对所有公开输入、输出端口都在对应帮助中出现。

## [0.2.1d] - 2026-08-08 — 专用 LM Studio 卸载节点

- **新增节点 `APS_UnloadModel`（Unload LM Studio Model）**：连接在 LLM 提示词与后续生成节点之间，卸载 LM Studio 后原样透传 prompt；填写 `model`（LM Studio v1 的 `key` 字段）+ 可选 `url`（默认 `http://127.0.0.1:1234`）。
- **复用同一服务层**：与 Runtime Control 节点、Settings /runtime 路由共用 `services/runtime/control.run_runtime_action`（固定 `backend=lmstudio`）；`instance_id` 解析仍由 `LMStudioBackend.unload` 负责（缓存 + v1 `loaded_instances[].id` 反查），走官方 `POST /api/v1/models/unload`，请求体 `{"instance_id": ...}`。
- **输出**：透传 `prompt` + `result`（JSON：ok / model / instance_id / error）+ `status`（可读中文文本）；副作用节点每次排队强制执行，不复用缓存。
- 注册：`nodes/__init__.py`、根 `__init__.py` 各加一项（当时为 10 个节点）；新增 `tests/test_nodes_unload.py`（成功 / 空 model 不误发 / 后端错误 / 不可达）。
- 文档：README 功能总览 + 节点说明表。

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

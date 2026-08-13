# 决策记录 decisions.md
> 本文件按时间保留历史决策。涉及 Prompt Composer、H3 Director、operation、
> 独立审批、Semantic Critic 或创意自动修复的旧条目均由 ADR 0007 取代。

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
- 档案元数据存 `config.json`；密钥单独存 `user/<pkg>/secrets.json`（ComfyUI user 目录）。前端只回脱敏值（`sk-***abcd`），后端按 `profile_id` 解析密钥。
- 工作流 JSON 只保存 `profile_id`，绝不包含密钥；日志只输出脱敏值。

## D4. 冒烟测试

- 独立端口 + `--cpu` headless 启动用户 ComfyUI，验证 `/object_info` 含 11 节点、前端资源和设置路由，验完即关；不碰运行中的实例。
- **环境复核（2026-08-08）**：`standalone-env` 本身不含 torch，但实际运行环境位于 `ComfyUI/.venv`。使用该解释器在 8388 端口成功启动 ComfyUI 0.31.1，并连续两次执行卸载节点缓存契约。
- **替代冒烟（等价验证，已实现为 pytest 用例）**：
  1. `tests/test_smoke_loader.py`：复刻 ComfyUI `spec_from_file_location` 加载语义，验证扩展、`WEB_DIRECTORY` 与 11 个节点完整注册。
  2. `tests/test_smoke_routes.py`：伪造 `server.PromptServer.instance.routes`（与用户 ComfyUI 一致的 `web.RouteTableDef()`），用真实 aiohttp 起临时 HTTP 服务做端到端往返（状态/档案 CRUD/密钥隔离/404/400/设置/Markdown 补充资料），验证路由注册与处理器接线。
- 结论：本扩展不依赖 ComfyUI 启动即可完整加载与验证；真实启动冒烟保留到用户补齐 torch 后（Phase 6 视环境情况执行或沿用替代冒烟）。

## D5. Schema 用 dataclass 而非 pydantic

- 理由：venv（3.13.12）与测试环境（系统 3.13.11）保持零第三方依赖一致；pydantic v2 虽在 venv 可用但测试环境未装。
- 所有 Schema：dataclass + `schema_version` + `migrations` 注册表（`upgrade(data)->data`）+ `to_json`/`from_json`（输入容错：忽略未知键、缺失键取默认）。

## D6. HTTP 层

- `requests` 同步 + SSE 流式解析；节点在 ComfyUI 工作线程内执行；取消通过共享 `stop_event` + 轮询检查。
- 超时/重试策略：生成连接超时 10s、读超时可配置（默认 120s）；生成 POST 不自动重试（防重复扣费）。手动完整能力探测会发送独立最小 POST，每项只执行一次。
- 错误按 HTTP 状态码归一化；`error.code` 视为可选。
- reasoning 参数：Responses 用 `reasoning.effort`（off 不发该字段）；Chat Completions 用 `reasoning_effort`，**仅当 provider=deepseek 时发送**（通用 OpenAI 兼容端点对未知参数可能 400）。同理 `response_format`(json) 仅 deepseek 发送。
- usage 命名差异：Responses `input/output_tokens`，Chat `prompt/completion_tokens`，adapter 统一映射为 LLMResult.usage（`accumulate_usage`）。

## D7. 联网搜索范围（v1）

- 只做 DeepSeek Responses 原生 `web_search` 工具 + 离线降级（带明确警告）；外部搜索后端留可插拔接口（services/search.py），不强制第三方 Key。
- 降级链：Responses 原生 → Responses function tool → Chat function tool → 外部后端 → 离线+警告。
- 401/402/403/429/5xx/网络失败**不静默降级**；只有「接口/参数不支持」触发协议降级。

## D8. 视觉模型

- 档案支持通用 OpenAI 兼容视觉端点（`vision_model` 必填，`vision_base_url` 留空复用主 `base_url`），图片 base64 data URL 编码调用（用户访谈确认）。
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

- **镜头检查只扫描描述字段/段**：`SHOT_RE` 会误匹配首行对齐指令里的 `(from [Shot 1])` 与 retention_analysis 段的 `[Shot N]` 引用，因此 `_check_shots` 只在 `integrated_multimodal_description`（四模式）或 `detailed_description`（Ref2VA）内找镜头。
- **畸形时间戳独立检测**：`SHOT_RE` 只捕获合法 `MM:SS.mmm`，格式错误的 `At XX:XX:XXX` 会被当成「缺失时间戳」；新增 `AT_RE` 单独捕获并报 `h3_ts_format`。
- **`<d>` 语言标注独立检测**：`DIALOGUE_RE` 需要 `[Language]` 才匹配，缺失语言标注的对白匹配不上；改为对每个 `<d>` 直接检查其后是否紧跟 `[`。
- **H3 Model Core + Markdown 参考**：`prompting/model_cores.py` 保存不可编辑的协议/内容硬规则；用户 Markdown 只能作为带来源的低优先级参考。renderer/validator 中不可变的格式协议仍由代码强制。repair 把校验问题回灌给 LLM，一次修复后重新渲染并复验。
- **历史决定（已由 PH5 取代）**：旧 H3 Director 曾以 `convert_storyboard` 做离线回退；当前 H3 Studio 要求模型成功产生可校验 Plan，协议只允许一次保真重试，失败不提交。
- **图片映射**：`map_image_assets` 按模式把输入图映射为 Picture 资产——I2VA 首帧（0.00s）、FL2VA 首尾（0.00s / 有效时长）、L2VA 尾帧（有效时长）；已存在的标签跳过不重复。

## D16. ANIMA 默认自然语言（2026-08-07）

- ANIMA 默认 `prompt_mode=natural_language`；tags/hybrid 保留为显式选项。
- Character Bible 稳定/锁定特征自然融入散文正文，绝不降级为 tag soup。
- 结构化 `AnimaPromptPlan`（人物绑定/正文/标签/风格/环境/构图/光照）供 Natural/Tags/Hybrid 三渲染器消费，Hybrid = 小段控制标签块 + 自然正文，杜绝正文重复成标签。

## D17. CharacterBook 与 Speaker ID 唯一分配（2026-08-07）

- `CHARACTER_BOOK` 类型；Character Bible 节点可选输入已有 Book，输出 CHARACTER_BIBLE + CHARACTER_BOOK 双路。
- 单个 CharacterBible 不再默认 `speaker_id="S1"`（曾导致多人物全部撞号）；唯一 ID 由 `CharacterBook.assign_speaker_ids()` 分配：既有 ID 稳定、删除不改动他人、新人物取下一个可用、冲突修复并记 warning。
- 节点按「同名」复用 Book 中已有档案（保留 character_id / Speaker ID / 锁定），更新不产生重复条目。

## D18. H3 媒体独立编号 + Ref2VA 英文 + 模式资产约束（2026-08-07）

- Picture/Video/Audio 按类型独立 1 起始连续编号（`normalize_media_labels` 渲染前确定性重排），manifest 标签可回溯到原始资产。
- Ref2VA 六段正文必须英文；检测到非英语 → 一次 LLM 修复（auto_repair，默认开）；仍失败 → validation 记 `h3_ref2va_english` 错误，不做假装翻译。`<d>` 对白/歌词/画面文字保留原语言。
- 模式资产约束：T2VA=0 图、I2VA=1、FL2VA=2、L2VA=1、Ref2VA 不限；不满足记 error 且不生成错误引用。

## D19. 采样参数进档案高级设置（2026-08-07）

- temperature/top_p/frequency_penalty/presence_penalty/max_tokens **不进普通节点 UI**；只存在于档案高级设置，None = 不发送字段（provider 默认值）。
- LLM Generate 节点移除 max_tokens 控件；生成请求采样值来自档案。
- 用户 system_prompt 以真实 system 指令发送（内部守则层在前 + 用户 system_prompt，不静默丢弃）。

## D20. API 附件（2026-08-07）

- `ATTACHMENT` / `ATTACHMENT_LIST` 类型；LLM Generate 可选输入 + 本机文件路径控件（相对 input 目录）。
- 协议映射（官方文档查证）：Responses `input_image`（image_url data URI）/ `input_file`（file_data+filename）/ `input_text`；Chat `image_url` parts / `{"type":"file","file":{...}}` / text parts。
- 降级规则：文本附件全协议可用；图片附件要求视觉能力（caps.vision 或档案 supports_vision），否则**报错不静默**；文件附件要求 supports_files，否则报错。
- 安全：路径必须解析在 input 目录内（拒绝穿越/绝对路径绕过）、大小上限（文本 512KB/图 20MB/文件 20MB）、内容不进日志。

## D21. 结构化输出（2026-08-07）

- Gateway `OutputContract`：对应协议的主动探测 `structured_output_responses/chat=True` → 发送契约机器 schema（Responses `text.format` / Chat `response_format.json_schema`）；否则从同一契约派生提示词约束 + 解析校验。第三方端点不再按 provider 名猜测。

## D22. Batch C：共享运行时服务层 / 外部搜索 / 工具循环 / 卸载策略（2026-08-07）

- Settings `/runtime` 与 Runtime Control 节点共用 `services/runtime/control.run_runtime_action`（同一服务层，杜绝两处实现漂移）；`custom` 是真实适配器（status 走 `GET /v1/models`，load/unload 走 `POST /models/{load,unload}` body `{"model": ...}`），非摆设选项。
- 外部搜索后端：无原生 web_search 且档案配置 `search_url` 时，网关把 `POST {query} → {results:[{title,url,snippet}]}` 的结果块注入最后一条 user 消息；失败 → 明确警告并离线执行，绝不伪造结果。
- 函数工具循环：`MAX_TOOL_ROUNDS=4`（不暴露到节点 UI）；工具注册表（`now`/`search`）；执行失败把错误文本回给模型继续，不抛异常；达到上限仍有 tool_calls → 截断警告不静默丢弃。
- 本地运行时卸载策略：`unload_policy` 仅对 `provider=local` 生效；`after_request`=请求结束即卸载（无论成败），`after_success`=仅成功时卸载；卸载失败只追加 warning，不影响请求结果。

## D23. Batch D：多图身份判断 / 视觉文本 Profile 解耦 / Manifest 消费 / Markdown supplement 管理（2026-08-07）

- 多图身份判断：`identity_agreement`（stable 特征名与值一致比例）→ `cluster_by_identity` 贪心聚类 → `judge_identity` 判定 `same_subject`；多主体时只合并最高一致度分组（防跨主体串绑），其余图记 `__subject_identity__` 冲突。
- 视觉/文本 Profile 解耦：`AIProfile.vision_profile_id` 指向另一档案时，视觉分析默认直接使用目标档案的主 `base_url + model + key`（目标档案显式设置 `vision_*` 时优先）；留空才使用本档案的 `vision_base_url + vision_model + key`。设置页在关联状态停用会被忽略的本地视觉字段。文本生成始终使用原文本档案。
- Storyboard 消费 Manifest：character 类 Subject 补成 `[角色表（来自参考清单）]` 并沿用真实 subject_id；已有 CharacterBook 时以 book 为准不重复注入；其余资产/主体进 `[可用参考资产]`。
- Markdown supplement 管理：本地 `.md` 资料支持导入、查看、编辑、删除、启停与范围绑定；大小/UTF-8/路径/哈希校验；新增 `/supplements` 路由（list/get/create/update/delete/enabled）。

## D24. 0.2.1 Hardening 关键决策（2026-08-07）

- **ANIMA Safety 标签产品决策（补充 P0）**：官方 safety 标签全集 `safe/sensitive/nsfw/explicit`；`safe` 只是官方示例默认，不是所有 Prompt 的强制项。节点参数 `content_tier` 重新设计为 `safety_tag ∈ none/safe/sensitive/nsfw/explicit`，**默认 none = 不注入任何 Safety 标签**（Composer 不在用户未要求时给提示词增加内容语义）。旧工作流 `content_tier=safe/sensitive` 自动迁移到 `safety_tag`。三种 prompt_mode（natural/tags/hybrid）统一尊重；用户节点参数优先级 > Prompt Plan 建议 > 无标签（`none` 时即使 LLM Plan 输出 safe 也不插入）；Composer 只按用户选择渲染，不做内容审查、不自动改等级；Validator 只查格式（最多一个 safety 标签、位于官方 safety 段），`nsfw/explicit` 不是语法错误。
- **历史决定（已由 ADR 0007 / PH5 取代）**：旧 Composer/Director 的 audit、convert 与 tags 分支已经删除。当前 Studio 只提供 Session 推断的 CREATE/REFINE；确定性 validator 不作为用户 operation 暴露。
- **DeepSeek 结构化输出按协议判定**：Responses 路径 `structured_output_responses=True`（flash，官方 `text.format` 支持）→ 原生 `{"text":{"format":{"type":"json_schema",...}}}`；Chat 路径未文档化 json_schema → 提示词约束+解析修复。旧 `structured_output` 字段保留为协议级能力的聚合（设置面板展示）。
- **Responses call_id 以模型返回为准**：SSE 参数 delta 按 `item_id` 累积，`call_id` 取 function_call 输出项的权威值；续轮 `function_call_output` 逐字沿用，绝不伪造 `call_N`。
- **LM Studio v1 优先 + instance_id 卸载**：探测顺序 v1 → v0 → unavailable；unload 请求体 `{"instance_id": ...}`（用户只传 model 时从 load 响应或 `loaded_instances` 解析）。
- **附件文档解析一致性（方案 A 实现）**：PDF/DOCX 在 Provider 无 file 能力时本地提取文本（pypdf/python-docx，可选依赖）→ `Attachment(kind=text)` + warning「已本地提取文本发送」；扫描件无文本层/非 PDF/DOCX/依赖缺失 → 明确报错，不 OCR、不假装识别。PPTX/XLSX 不在本轮（文档明确只支持 PDF/DOCX 本地提取）。
- **多图身份判断增加一次 VLM 整体判断**：`batch_identity_check`（最多 6 张代表图；"Do these images show the same visual subject?"，只比较可观察身份特征，服装/背景/姿势为弱辅助）；VLM 失败回退 deterministic heuristic；身份判断提示词禁止以「衣服/背景/姿势相同」为主要依据。
- **H3/Storyboard 原生 Structured Output**：`H3_SCHEMA` / `STORYBOARD_SCHEMA` 由 `OutputContract` 持有（Provider 支持时走协议层，否则从同一 schema 自动派生约束），避免 System 规则 + 巨大 JSON 示例 + Provider Schema 三重重复。
- **Schema.from_json 接受 JSON 字符串**：ComfyUI 自定义类型输入可能以 JSON 字符串到达（之前对 str 直接抛 SchemaError 导致自定义类型无法接线）；现在字符串先解析为 dict 再反序列化，保持输入容错。

## D25. 0.2.1a 小补丁决策（2026-08-07）

- **LM Studio v1 模型标识以官方 `key` 为准**：官方 `GET /api/v1/models` 条目的模型标识字段是 `key`（`id` 只存在于 `loaded_instances` 实例条目）；解析兼容 `key`/`id` 两代结构，测试改用官方真实结构（此前测试 mock 与代码用了同一错误字段，掩盖了独立 unload 找不到 instance 的缺陷）。
- **VLM 身份判断为 merge 权威**：`identity_consensus_with_verdict` —— same_subject=True 直接合并全部候选（VLM confidence 写入 identity_confidence）；False 禁止全量合并（主主体 + `__subject_identity__` 冲突，防串绑）；VLM 失败才回退字符串一致度启发式。旧字符串算法只作 fallback，不再覆盖 VLM 结论。
- **CharacterBook 全量进 Generic/SDXL/FLUX**：render_generic 新增 `book` 参数，多人物全部渲染（不再只取 first_bible）；Composer 确定性/LLM 路径都传 book；主链路测试改为 text 只写剧情、特征全部来自 CharacterBook。
- **Responses adapter 补 `import json`**：兼容端点 function_call arguments 为 dict 时不再 NameError。
- **附件：无点扩展名比较 + UTF-8 字节截断**：`_document_extractable` 用无点小写（pdf/docx）；`local_extract_document` 按 UTF-8 字节截断并回退到有效字符边界（中文长文档不再超 512 KB）。
- **Gateway 降级重算 Structured Output**：协议切换（ProtocolUnsupported 降级）时按新协议重新调用 `_structured_output_for`，绝不把某协议不支持的 json_schema 发给另一协议（deepseek-v4-flash Responses→Chat 场景）；提示词约束注入幂等。

## D26. 0.2.1b 收尾决策（2026-08-07）

- **Natural 模式也消费 CharacterBook（默认路径修复）**：`render_generic` natural_language 分支由「原样返回 text」改为 `_natural_with_characters()`（每人物一句 `A, with <特征…>`，正文已含特征跳过）；Composer 全局默认 prompt_mode=natural_language 时 Generic/SDXL/FLUX 不再丢人物信息。
- **VLM same=false 在启发式无法分组时只取单图**：字符串一致度全聚成一组 ≠ 允许全量合并——取置信度最高的一张作主人物，其余保留身份冲突（真正的「VLM 否决合并」）。
- **Reference Analyzer 按需取 Key**：文本/视觉两个 Profile 各自按需 require（Text Provider ≠ Vision Provider）；只做图片分析时文本档案无 Key 也可运行。
- **PromptPlan metadata 全量**：character_bindings 记录 CharacterBook 全部人物（不只 first_bible）；Reference Analyzer 描述去掉「视频」文案。

## D27. 0.2.1c 前端入口决策（2026-08-07）

- **入口放入原生 Settings，不占 Sidebar**：不调用 `app.extensionManager.registerSidebarTab`，也不注入 `.comfy-menu`。ComfyUI Settings 页面显示 `AI Prompt Studio > General > Settings Workbench`，选择后调用现有 `openPanel()` 打开大型设置工作台 overlay。
- **Settings API 的动作限制**：官方 Settings API 支持 `boolean / text / number / slider / combo / color / image / hidden`，没有 button/action 类型。工作台入口采用一次性 combo `AI Prompt Studio.General.openWorkbench`：`idle`（默认）/ `open`；用户选择 `open` 后打开 overlay，并通过 `app.extensionManager.setting.set(id, "idle")` 自动复位，避免重启后重复动作。
- **原生设置项**：`AI Prompt Studio.General.language`（combo zh/en）+ `AI Prompt Studio.General.openWorkbench`（动作 combo）。**API Key 不进前端设置**——密钥存储保持服务端 SecretStore，工作台只显示脱敏值。
- **重复打开防护**：`openPanel()` 复用 `#aps-overlay`（`panel || getElementById`），不重复建面板。
- **诊断日志**：加载与 Settings 注册都有 `[AI Prompt Studio]` 前缀的 `console.info`；动作复位失败 `console.warn`；只打状态，不打印 API Key / 提示词 / 附件内容。
- **前端可测性**：Settings 配置与动作通过真实 ComfyUI 0.30.2 + frontend 1.47.12 浏览器验收；生产 `settings.js` 不依赖 Sidebar 入口模块。

## D28. 主动能力探测（2026-08-08）

- `/models` 只负责认证线索与模型下拉，不再推断 Chat、Responses、Schema、工具或多模态能力。
- 用户手动点“重新探测”后，按运行时实际请求格式逐项发送最小非流式请求：Chat、Responses、Chat/Responses JSON Schema、Chat JSON Object、两协议函数工具、两协议图片、两协议文件、Responses web_search，以及独立视觉模型 Chat。
- HTTP 200 不是能力成功的充分条件：JSON 必须可解析且等于固定对象，工具必须返回指定 function call，图片必须识别 8×8 洋红测试图，文件必须读回随机标记，联网必须出现 web search call。
- 有 API Key 且完成执行探针后，运行能力只存 bool，不留 unknown；每项保存端点、HTTP 状态和失败原因。认证失败会停止后续探针，避免连续无效请求。
- 完整探测会消耗少量 token，设置页点击前必须明确确认；“测试连接”只运行目录和两条最小文本协议测试。
- 主模型 `vision/files` 与 Reference Analyzer 的 `vision_service` 分开；auto 协议按 `vision_chat/responses`、`files_chat/responses` 和 `function_tools_chat/responses` 选择真正通过探针的路径。
- 探测完成会把 `supports_vision/supports_files` 回写为实测聚合结果；Profile/Key 变化或 probe 版本升级使缓存指纹失效。

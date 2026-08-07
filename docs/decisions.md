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

## D16. ANIMA 默认自然语言（2026-08-07）

- ANIMA 默认 `prompt_mode=natural_language`；tags/hybrid 保留为显式选项。
- Character Bible 稳定/锁定特征自然融入散文正文，绝不降级为 tag soup。
- 结构化 `AnimaPromptPlan`（人物绑定/正文/标签/风格/环境/构图/光照）供 Natural/Tags/Hybrid 三渲染器消费，Hybrid = 小段控制标签块 + 自然正文，杜绝正文重复成标签。

## D17. CharacterBook 与 Speaker ID 唯一分配（2026-08-07）

- `CHARACTER_BOOK` 类型；Character Bible 节点可选输入已有 Book，输出 CHARACTER_BIBLE + CHARACTER_BOOK 双路。
- 单个 CharacterBible 不再默认 `speaker_id="S1"`（曾导致多人物全部撞号）；唯一 ID 由 `CharacterBook.assign_speaker_ids()` 分配：既有 ID 稳定、删除不改动他人、新人物取下一个可用、冲突修复并记 warning。
- 节点按「同名」复用 Book 中已有档案（保留 character_id / Speaker ID / 锁定），更新不产生重复条目。

## D18. H3 媒体独立编号 + R2V 英文 + 模式资产约束（2026-08-07）

- Picture/Video/Audio 按类型独立 1 起始连续编号（`normalize_media_labels` 渲染前确定性重排），manifest 标签可回溯到原始资产。
- R2V 六段正文必须英文；检测到非英语 → 一次 LLM 修复（auto_repair，默认开）；仍失败 → validation 记 `h3_r2v_english` 错误，不做假装翻译。`<d>` 对白/歌词/画面文字保留原语言。
- 模式资产约束：T2VA=0 图、I2VA=1、FL2VA=2、L2VA=1、R2V 不限；不满足记 error 且不生成错误引用。

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

- Gateway `output_schema`：能力允许（非 DeepSeek 且 caps.structured_output=True）→ 协议层 schema（Responses `text.format` json_schema / Chat `response_format.json_schema`）；否则降级为提示词约束 + 解析校验（DeepSeek 未文档化 json_schema，不发送该参数）。

## D22. Batch C：共享运行时服务层 / 外部搜索 / 工具循环 / 卸载策略（2026-08-07）

- Settings `/runtime` 与 Runtime Control 节点共用 `services/runtime/control.run_runtime_action`（同一服务层，杜绝两处实现漂移）；`custom` 是真实适配器（status 走 `GET /v1/models`，load/unload 走 `POST /models/{load,unload}` body `{"model": ...}`），非摆设选项。
- 外部搜索后端：无原生 web_search 且档案配置 `search_url` 时，网关把 `POST {query} → {results:[{title,url,snippet}]}` 的结果块注入最后一条 user 消息；失败 → 明确警告并离线执行，绝不伪造结果。
- 函数工具循环：`MAX_TOOL_ROUNDS=4`（不暴露到节点 UI）；工具注册表（`now`/`search`）；执行失败把错误文本回给模型继续，不抛异常；达到上限仍有 tool_calls → 截断警告不静默丢弃。
- 本地运行时卸载策略：`unload_policy` 仅对 `provider=local` 生效；`after_request`=请求结束即卸载（无论成败），`after_success`=仅成功时卸载；卸载失败只追加 warning，不影响请求结果。

## D23. Batch D：多图身份判断 / 视觉文本 Profile 解耦 / Manifest 消费 / Skill 管理（2026-08-07）

- 多图身份判断：`identity_agreement`（stable 特征名与值一致比例）→ `cluster_by_identity` 贪心聚类 → `judge_identity` 判定 `same_subject`；多主体时只合并最高一致度分组（防跨主体串绑），其余图记 `__subject_identity__` 冲突。
- 视觉/文本 Profile 解耦：`AIProfile.vision_profile_id` 指向另一档案时，视觉分析使用该档案的 vision_* 配置与密钥；留空用本档案。文本生成始终用本档案 base_url/model。
- Storyboard 消费 Manifest：character 类 Subject 补成 `[角色表（来自参考清单）]` 并沿用真实 subject_id；已有 CharacterBook 时以 book 为准不重复注入；其余资产/主体进 `[可用参考资产]`。
- Prompt Skill 管理：内置（仓库 skills/，只读）+ 自定义（用户配置目录 skills/，可增删改/启停/复制内置）；字段白名单 + renderer/family 枚举校验 + hash 审计；新增 `/skills` 路由（list/get/create/update/delete/enabled）。

## D24. 0.2.1 Hardening 关键决策（2026-08-07）

- **ANIMA Safety 标签产品决策（补充 P0）**：官方 safety 标签全集 `safe/sensitive/nsfw/explicit`；`safe` 只是官方示例默认，不是所有 Prompt 的强制项。节点参数 `content_tier` 重新设计为 `safety_tag ∈ none/safe/sensitive/nsfw/explicit`，**默认 none = 不注入任何 Safety 标签**（Composer 不在用户未要求时给提示词增加内容语义）。旧工作流 `content_tier=safe/sensitive` 自动迁移到 `safety_tag`。三种 prompt_mode（natural/tags/hybrid）统一尊重；用户节点参数优先级 > Prompt Plan 建议 > 无标签（`none` 时即使 LLM Plan 输出 safe 也不插入）；Composer 只按用户选择渲染，不做内容审查、不自动改等级；Validator 只查格式（最多一个 safety 标签、位于官方 safety 段），`nsfw/explicit` 不是语法错误。
- **职责解耦：只有 LLM 路径才 require_api_key**：Prompt Composer 的 audit / convert / generate(tags)（Python renderer 确定性路径）与 ANIMA audit 完全离线；H3 Director 的 audit 完全离线，`convert_storyboard` 支持无 API 的纯 Python 确定性转换（有 API 时 LLM 增强）。
- **DeepSeek 结构化输出按协议判定**：Responses 路径 `structured_output_responses=True`（flash，官方 `text.format` 支持）→ 原生 `{"text":{"format":{"type":"json_schema",...}}}`；Chat 路径未文档化 json_schema → 提示词约束+解析修复。旧 `structured_output` 字段保留为协议级能力的聚合（设置面板展示）。
- **Responses call_id 以模型返回为准**：SSE 参数 delta 按 `item_id` 累积，`call_id` 取 function_call 输出项的权威值；续轮 `function_call_output` 逐字沿用，绝不伪造 `call_N`。
- **LM Studio v1 优先 + instance_id 卸载**：探测顺序 v1 → v0 → unavailable；unload 请求体 `{"instance_id": ...}`（用户只传 model 时从 load 响应或 `loaded_instances` 解析）。
- **附件文档解析一致性（方案 A 实现）**：PDF/DOCX 在 Provider 无 file 能力时本地提取文本（pypdf/python-docx，可选依赖）→ `Attachment(kind=text)` + warning「已本地提取文本发送」；扫描件无文本层/非 PDF/DOCX/依赖缺失 → 明确报错，不 OCR、不假装识别。PPTX/XLSX 不在本轮（文档明确只支持 PDF/DOCX 本地提取）。
- **多图身份判断增加一次 VLM 整体判断**：`batch_identity_check`（最多 6 张代表图；"Do these images show the same visual subject?"，只比较可观察身份特征，服装/背景/姿势为弱辅助）；VLM 失败回退 deterministic heuristic；身份判断提示词禁止以「衣服/背景/姿势相同」为主要依据。
- **H3/Storyboard 原生 Structured Output**：`H3_SCHEMA` / `STORYBOARD_SCHEMA` 作为 `GenerateRequest.output_schema`（Provider 支持时走协议层，否则自动降级提示词约束），避免 System 规则 + 巨大 JSON 示例 + Provider Schema 三重重复。
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
- **前端可测性**：Settings 配置与动作通过真实 ComfyUI 0.30.2 + frontend 1.47.12 浏览器验收；生产 `settings.js` 不依赖 Sidebar/legacy 入口模块。

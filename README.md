# ComfyUI AI Prompt Studio

面向 ComfyUI 的 LLM 提示词工作流扩展（AI 提示词工作室）。把「剧情构思 → 人物档案 → 分镜 → 目标模型提示词」整条链路搬进 ComfyUI 节点图，覆盖 **ANIMA** 与 **MiniMax H3** 两类生成式视频模型的官方提示词规范。

11 个节点，统一分类 **`AI Prompt Studio`**，类名统一 **`APS_`** 前缀。

---

## 功能总览

- **统一 LLM 网关**：主动实测后选择 Responses / Chat Completions；支持任意 OpenAI 兼容端点及本地运行时（Ollama / llama.cpp / LM Studio）。
- **AI Model Profile**：命名服务档案 + 主动能力探测 + 密钥安全存放（密钥永远不进工作流 JSON）。探测会用运行时相同请求格式验证文本、JSON、工具、联网、图片和文件，不再从 `/models` 猜能力。
- **Reference Analyzer**：文本锚点 / 图片特征反推，多图共识与冲突，人物来源证据，输出参考资产清单。
- **Character Bible**：人物稳定身份（stable / variable / current / uncertain），5 种合并策略，字段锁定，冲突报告，H3 说话人 ID。
- **Storyboard Builder / Select**：模型无关的剧情分镜（场景 / 镜头 / 节拍），选择与批处理，不写目标模型格式。
- **Image Prompt Studio**：`APS_PromptStudio` 覆盖 ANIMA、Z-Image Turbo、Qwen-Image-Edit-2511 与 Generic Image。默认 `lenient` 直接维护完整提示词，适合本地小模型；`strict` 使用结构化 Plan、ChangeSet、Diff Guard 与原子 revision。两种模式都自动从 Session 判断 CREATE/REFINE，不再提供 operation 下拉。旧 v1/v2 Session 会重置为空 v3；最近保留 10 个成功版本。
- **图片引用提示词**：连接图片后在输入框键入 `@`，带缩略图选择 `@图1`；自动转换为 Qwen `Figure 1` 或 H3 `<Picture 1>`。
- **MiniMax H3 Prompt Director**：T2VA / I2VA / FL2VA / L2VA / Ref2VA（另保留旧 R2V 别名），支持图片、视频和音频参考；LLM 产出结构化计划 + Python 确定性渲染 + 规则校验 + 修复循环。
- **结构化输出容错**：H3 CREATE Plan 或 Studio REFINE ChangeSet 首次出现非 JSON、重复路径或缺少授权范围时，会在不修改当前 revision 的前提下最多重试一次；仍失败会显示并记录截断的模型原始输出，便于区分 provider 降级、截断和格式漂移。
- **P4.1 原子恢复接缝**：Session 提交携带 transaction/base/result revision，并可先写入按节点实例隔离的 Recovery Journal；当前提供线程安全内存参考实现，持久化工作流回写留给 P5。确定性影响分析会自动闭合 positive/negative 冲突和 H3 duration→镜头时间戳依赖，并把实际依赖与修复次数写入 revision。
- **Local Runtime Control**：Ollama / llama.cpp / LM Studio 的加载、卸载、状态查询。
- **Unload LM Studio Model**：串接在 LLM prompt 输出与后续生成节点之间，按 `instance_id` 卸载 LM Studio 后原样透传 prompt，先释放外部 LLM 显存再加载图像/视频模型。
- **设置工作台**：ComfyUI 内嵌面板，提供档案、密钥（脱敏）、API 测试、能力状态、运行时和 Prompt Skill 查看/新建/编辑；H3 节点另有镜头草稿导演工作台。
- **前端入口（0.2.1c）**：不占用 ComfyUI Sidebar；入口放在 ComfyUI 原生 **Settings** 页面中的 `AI Prompt Studio > General > Settings Workbench`。选择「Open Settings Workbench」打开大型设置工作台；语言也在同一组设置中切换。API Key 不进原生 Settings，仍由工作台填写并只存服务端。

## 安装

> 目标环境：Windows 11 · ComfyUI 0.30.x · Python 3.10+。硬依赖只有 `requests` + `PyYAML`（视觉分析另需 Pillow/numpy，ComfyUI venv 自带），**不需要 torch / CUDA**，CPU 环境可加载全部节点。

```bash
cd E:\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI\custom_nodes
git clone https://github.com/Liuxd-1230/ComfyUI-AI-Prompt-Studio.git
# 重启 ComfyUI；无需安装任何大依赖（requests 一般已存在）
# 可选：PDF/DOCX 附件本地文本提取（0.2.1）——不装则此类附件在无原生文件支持时明确报错
pip install "pypdf>=4.0" "python-docx>=1.1"
```

卸载：删除 `custom_nodes/ComfyUI-AI-Prompt-Studio` 目录即可（不修改 ComfyUI 核心，无残留配置以外的写入）。

## 快速开始

1. 启动 ComfyUI，打开 **Settings（Ctrl+,）** → **AI Prompt Studio** → **General**，选择 **Open Settings Workbench**。
2. 新建档案，选择 provider、API 根地址和模型，保存后填写 API Key（只保存在本机 `user/ai_prompt_studio/secrets.json`）。先点“测试连接”，再点“重新探测”。
3. “重新探测”会明确提示并发送最小请求，消耗少量 token；完成后检查 Chat/Responses/JSON/工具/图片/文件勾选与失败详情。
4. 在节点图中放置 **AI Model Profile**，直接从“档案名称 [ID]”和该档案的模型目录下拉选择。
5. 图像提示词放置 **Image Prompt Studio**；H3 暂用 **MiniMax H3 Prompt Director**（双通道替换进行中）。连接 `AI_PROFILE`，第一次填完整要求；成功后只填本轮修改意见。小型本地模型优先用 `lenient`，需要结构化变更审计时再选 `strict`。
6. H3：把 `prompt`（STRING）接到 H3 生成节点；图像模型：把 `positive` / `negative` 接到采样链路。

示例工作流见 [`examples/`](examples/)：
- `h3_full_chain.json` — H3 全链路（Profile → H3 Director → STRING）
- `anima_full_chain.json` — ANIMA 全链路（Profile → Storyboard → Select → Prompt Studio）
- `aps_usage_showcase.json` — Z-Image、Qwen 图片引用和 LLM 生成后卸载

示例均不含密钥。

## 节点说明

完整的每个输入/输出端口、连接方向和类型说明见 [节点端口参考](docs/node-reference-zh.md)；所有枚举模式、期待输入与成品示例见 [模式与提示词示例](docs/prompt-mode-examples-zh.md)。这些内容也同步到 ComfyUI 节点内的中文帮助页。

| 节点 | 功能 | 关键输入 | 关键输出 |
|---|---|---|---|
| **AI Model Profile** | 选择档案、覆盖模型/协议/联网/卸载策略 | profile / protocol / reasoning | `AI_PROFILE` |
| **LLM Generate / Chat** | 通用对话/生成（流式、推理、联网、会话） | `AI_PROFILE`、prompt | `LLM_RESULT`、`CHAT_SESSION` |
| **Reference Analyzer** | 文本/图片参考分析（11 种模式） | `AI_PROFILE`、text、images | `REFERENCE_ANALYSIS`、`CHARACTER_CANDIDATE`、`REFERENCE_MANIFEST`、IMAGE 透传 |
| **Character Bible** | 合并人物特征、锁定、冲突报告 | `CHARACTER_CANDIDATE`、`existing_bible` | `CHARACTER_BIBLE`、人物提示片段 |
| **Storyboard Builder** | 剧情 → 结构化分镜（LLM） | `AI_PROFILE`、story_text | `STORYBOARD` |
| **Storyboard Select / Batch** | 场景/镜头/区间/全部选择（不调模型） | `STORYBOARD` | 单项、容器及真实 ComfyUI `STORY_ITEMS` 列表输出 |
| **Model Prompt Composer** | 持久图像 Plan：自动 CREATE/REFINE、不可变 revision 恢复 | `AI_PROFILE`、text、target、session | positive、negative、`PROMPT_PLAN`、validation |
| **图片引用提示词（输入 @）** | 图片连接 → 模型引用语法与资产清单 | prompt、target、image_1～3 | prompt、`REFERENCE_MANIFEST`、references、count |
| **MiniMax H3 Prompt Director** | 持久 H3 Plan：逐镜头最小修改、不可变 revision 恢复 | `AI_PROFILE`、text、mode、session、媒体 | prompt(STRING)、`H3_PROMPT_PLAN`、validation |
| **Local Runtime Control** | 本地模型加载/卸载/状态 | `AI_PROFILE`、action、backend | profile、status、loaded、op |
| **Unload LM Studio Model** | LLM 后卸载 LM Studio，并把提示词透传给后续生成 | prompt、model、url | prompt、result(JSON)、status(文本) |

节点之间用自定义数据类型（`AI_PROFILE` / `STORYBOARD` / `H3_PROMPT_PLAN` 等）传递结构化对象，工作流可读可保存。

## 能力探测如何判定

“测试连接”只执行模型目录和最小文本连接测试；“重新探测”执行完整矩阵。只有收到 HTTP 200 **且响应内容符合预期**才勾选：

- Chat/Responses：实际生成一条极短文本；
- JSON Schema/JSON Object：要求固定 JSON，并再次解析和比对，HTTP 200 但返回普通文本仍判失败；
- 函数工具：强制调用无参数测试函数，并检查真实 tool call；
- 图片：发送 8×8 洋红 PNG，模型必须识别颜色；
- 文件：发送带随机标记的极小文本文件，模型必须读回标记；
- 原生联网：使用运行时相同的 Responses `web_search` 工具并检查工具调用记录。

探测结果全部为明确 true/false，并记录端点、HTTP 状态和原因。重新探测失败会覆盖旧缓存；档案/模型/API Key 变化也会让旧结果失效。图片或文件实测失败时，设置页对应手动开关会取消，防止 Gateway 继续发送必失败的附件。主模型图片输入与 Reference Analyzer 的独立视觉模型分开显示。

请求结构分别遵循 [OpenAI Responses API](https://platform.openai.com/docs/api-reference/responses) 与 [DeepSeek Chat Completion](https://api-docs.deepseek.com/api/create-chat-completion)；结构化输出探针另按 [DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/) 校验返回内容。完整探测会产生少量模型调用与 token 消耗，因此只在用户点击“重新探测”时运行。

## ANIMA 提示词（官方档案）

- **Base**：前缀 `masterpiece, best quality, score_7, `（0.2.1 起 **不再强制注入 `safe`**，见下方 Safety 标签）+ 官方负面（`worst quality, low quality, score_1..3, artist name, blurry, jpeg artifacts, chromatic aberration`），建议 30-50 步 / CFG 4-5。
- **Aesthetic**：官方建议正负提示词都不用 `score_*` 标签，30-50 步 / CFG 4.5。
- **Turbo**：官方示例前缀 + **CFG 1 / 8-12 步**。
- 语法：小写标签、空格分隔（`score_*` 是唯一带下划线的标签）、`@artist` 艺术家前缀、标签分段排序（quality/meta/year/safety → count → artist → general）、LoRA 触发词原样保留追加。
- 支持 `tags` / `natural_language` / `hybrid` 三模式。
- **语言要求**：最终视觉描述与标签使用英文；Composer 的 ANIMA 扩写、改写和修复 Skill 会把中文输入保真转换为英文。角色名、专有名词与画面内文字可以保留原语言。
- **Safety 标签（0.2.1）**：节点参数 `safety_tag` ∈ `none / safe / sensitive / nsfw / explicit`，**默认 `none` = 不注入任何 Safety 标签**（Composer 不在用户未要求时给提示词增加内容语义，也不做内容审查——审查留给模型服务端）。官方模型卡推荐前缀包含 `safe`；本项目把它明确作为用户可选的产品覆盖，而不冒充官方默认。旧参数 `content_tier`（safe/sensitive）自动迁移。

## MiniMax H3（官方手册规则）

- **四模式（T2VA/I2VA/FL2VA/L2VA）**：首行对齐指令（I2VA 首帧锚定 / FL2VA 首尾帧路径、默认单镜头 / L2VA 尾帧收敛）+ 空行 + 三字段 `integrated_multimodal_description` / `overall_soundscape` / `non_diegetic_music`。
- **Ref2VA**（旧工作流 `R2V` 自动迁移）：六段 `subject_definitions` / `summary`（`[任务类型]` 前缀）/ `retention_analysis` / `detailed_description` / `overall_soundscape` / `non_diegetic_music`；图片≤9、视频≤3、音频≤3、混合≤12，视频总时长≤15 秒、音频总时长≤15 秒。
- 镜头 `[Shot 1]` 无时间戳，后续 `[Shot N] At MM:SS.mmm, ...` 严格递增；对白 `<d>[Language] ...</d>` 逐字保留原语言；说话人稳定 `(S1)` `(S2)`。
- 首行指令、时间戳和标签编号由 **Python 确定性渲染**；`validation` 仍会检查模型产生的语义、引用、媒体边界与声音字段，失败不会伪装成通过。
- 格式依据：[MiniMax-H3 官方 Skill](https://github.com/MiniMax-AI/MiniMax-H3/tree/main/skills/h3-prompt-writing)；实现差异与固定提交见 `docs/research/`。

## 安全模型

- **密钥不进工作流 JSON / 节点图 / git / 日志**：`AI_PROFILE` 节点载荷只含档案元数据（`node_payload()` 剔除 `api_key_ref`）；密钥只在设置工作台填写，存于 ComfyUI 用户目录的独立 `secrets.json`，接口一律脱敏返回。
- 日志对密钥脱敏（masked logs）。
- 不改 ComfyUI 核心：只注册节点、`WEB_DIRECTORY` 前端资源与 `/api/ai_prompt_studio/*` 路由（自动带 `/api` 前缀副本）。
- 不安装 CUDA/Torch 等大依赖；不把 Transformers 模型加载进 ComfyUI 进程。

## 兼容性

- **ComfyUI 0.30.x**：已隔离 `comfy.logging → comfy.internal_logging` 破坏性变更（本扩展不 import 核心日志）。
- **本地运行时**：Ollama / llama.cpp / LM Studio（v1 官方推荐；模型标识按官方 `key` 字段，`id` 仅存在于已加载实例 `loaded_instances` 条目；未达 v1 的旧版自动降级为 v0 只读状态查询）。
- **无 GPU 环境**：提示词相关功能只依赖 `requests` + `PyYAML`，可离线加载；联网功能（网关/探测）在无网络时明确报错，不伪装。
- **第三方共存**：MiniMax H3 采样三件套（Turbo / DualClock / TE-Speed）——H3 Director 只输出 STRING，不重复采样后端；ANIMA_BOOSTER 未安装时软检测提示，不硬依赖。
- 详见 `docs/compatibility.md`。

## 后端路由（设置工作台）

`/api/ai_prompt_studio/status` · `profiles`（GET/POST）· `profiles/{id}`（GET/PUT/DELETE）· `profiles/{id}/api_key`（POST/DELETE）· `profiles/{id}/probe` · `profiles/{id}/test` · `capabilities` · `log` · `settings`（GET/POST）· `runtime`。ComfyUI 会自动注册 `/api` 前缀副本。

## 开发与测试

```bash
python -m pytest tests/          # 全量测试（节点/网关/渲染器/校验器/安全/示例工作流）
node --check web/*.js            # 前端语法检查
python -m compileall nodes services renderers validators schemas server tests
```

- 测试覆盖加载器语义、aiohttp 路由回环、三后端 mock、H3/ANIMA 正反用例、示例工作流接口契约和主链路回归；数量以本地 `pytest` 结果为准。
- 架构与决策：`docs/decisions.md`、`docs/adr/`、`docs/compatibility.md`。
- P0-P4 架构基线、Prompt 来源/所有权/Assembly、事务、语义一致性与 Session/Revision 说明见 `docs/prompt-architecture/`。持久 REFINE 的低风险局部外观修改只跑确定性检查；动作、时间线、身份、参考和重大构图修改会用受影响 before/after 切片调用 Semantic Critic，错误或单次定向修复失败都不会覆盖上一 revision。四个目标模型的一手证据和本地差异见 `docs/prompt-sources/`。

## 许可与来源

MIT License（见 [LICENSE](LICENSE)）。目标提示词规范只采用模型作者的一手资料；固定版本、访问日期和本地差异见 `docs/prompt-architecture/official-source-ledger.md`。参考实现的边界见 `docs/licenses-and-sources.md`；不复制 ANIMA_BOOSTER / ComfyUI-Prompt-Assistant 内部实现。

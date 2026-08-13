# ComfyUI AI Prompt Studio

面向 ComfyUI 的 LLM 提示词工作流扩展（AI 提示词工作室）。把「剧情构思 → 人物档案 → 分镜 → 目标模型提示词」整条链路搬进 ComfyUI 节点图，覆盖 **ANIMA** 与 **MiniMax H3** 两类生成式视频模型的官方提示词规范。

11 个节点，统一分类 **`AI Prompt Studio`**，类名统一 **`APS_`** 前缀。

---

## 功能总览

- **统一 LLM 网关**：主动实测后选择 Responses / Chat Completions；支持任意 OpenAI 兼容端点及本地运行时（Ollama / llama.cpp / LM Studio）。
- **AI Model Profile**：命名服务档案 + 主动能力探测 + 密钥安全存放（密钥永远不进工作流 JSON）。探测会用运行时相同请求格式验证文本、JSON、工具、联网、图片和文件，不再从 `/models` 猜能力。
- **Reference Analyzer**：文本锚点 / 图片特征反推，多图共识与冲突，人物来源证据，输出参考资产清单。
- **Character Bible**：人物稳定身份（stable / variable / current / uncertain），5 种合并策略，字段锁定，冲突报告，H3 说话人 ID；角色表会把状态类别和来源证据传给分镜，默认不把 uncertain 推断当成硬事实。
- **Storyboard Builder / Select**：模型无关的剧情分镜（场景 / 镜头 / 节拍），选择与批处理，不写目标模型格式；确定性收敛场景上限、全片时长、重复 ID、空场景和人物显示名，并保留镜头/节拍声音。
- **Image Prompt Studio**：`APS_PromptStudio` 覆盖 ANIMA、Z-Image Turbo、Qwen-Image-Edit-2511 与 Generic Image。节点只维护可直接交给下游的完整提示词，自动从 Session 判断首次创建或继续修改。ANIMA 会确定性补齐质量前缀、输出基础负面词并合并用户明确写出的排除项；最近保留 10 个成功版本。
- **图片引用提示词**：连接图片后在输入框键入 `@`，带缩略图选择 `@图1`；自动转换为 Qwen `Figure 1` 或 H3 `<Picture 1>`。
- **MiniMax H3 Prompt Studio**：T2VA / I2VA / FL2VA / L2VA / Ref2VA（读取旧 R2V 值时归一化），支持图片、视频和音频参考，只维护完整官方 H3 文本。
- **H3 白描与动作连续性**：优先写主体位置、动作起点/路径/结果、路人反应与明确结尾，避免没有可视信息的堆砌形容词；未规定的小动作与环境细节可为连贯性补足。H3 文本节点不会直接看裸图片像素，Ref2VA 要获得可靠人物/场景细节应连接 Reference Analyzer 输出的 Manifest。
- **输出容错**：模型返回半截 JSON、半截标签或不满足确定性硬规则时，在不修改当前 revision 的前提下最多保真修复一次；仍失败会显示截断原文并保留上一版。
- **P5 持久会话恢复**：Session 提交先以 transaction/base/result revision 原子写入按节点实例隔离的 Recovery Journal，再回写工作流。异常退出后打开旧工作流时会明确询问是否恢复后端较新版本；复制节点会保留当前成品并建立独立 lineage，旧请求不能覆盖新 revision。日志位于 ComfyUI `user/ai_prompt_studio/recovery-journal.json`，最多保留最近 100 个节点会话。
- **Local Runtime Control**：Ollama / llama.cpp / LM Studio 的加载、卸载、状态查询。
- **Unload LM Studio Model**：串接在 LLM prompt 输出与后续生成节点之间，按 `instance_id` 卸载 LM Studio 后原样透传 prompt，先释放外部 LLM 显存再加载图像/视频模型。
- **设置工作台**：ComfyUI 内嵌面板，按档案、能力、本地运行时、Markdown/日志分区懒加载；支持 Esc 关闭和键盘焦点循环。
- **Model Core + Markdown 参考**：目标模型的硬规则由仓库内不可编辑 Model Core 持有；用户 Markdown 通过节点默认收起的 **高级设置 · Prompt Supplements** 选择（`auto` 仅用于目标节点），作为带来源/hash 的低优先级参考，不能覆盖协议、Schema、锁定事实或 validator。单份资料最多 256 KiB，每次最多 8 份、总上下文最多 128 KiB；工作流只保存稳定 ID。
- **统一操作策略**：CREATE、REFINE、格式修复、协议重试和参考观察由同一版本化 Operation Policy 接口提供。REFINE 只表达本轮增量并保留无关内容；修复只处理明确问题且最多一次。旧 operation 和 execution mode 下拉均已删除。
- **机器输出契约**：JSON Schema、`<PROMPT>/<SUMMARY>` envelope、JSON-only 模式和 provider fallback 由统一 `OutputContract` 持有。支持原生 Structured Output 时发送机器 Schema；不支持时从同一 Schema 自动派生约束，不再手抄 JSON 示例。输出契约是最后一个 system 层，Markdown 资料不能覆盖它。
- **前端入口**：不占用 ComfyUI Sidebar；在 **Settings → AI Prompt Studio** 点击“打开 AI Prompt Studio 设置工作台”即可进入。API Key 不进原生 Settings，仍由工作台填写并只存服务端。Studio 会检查前后端版本；更新节点包后若看到“需重启”，请重启 ComfyUI，不要在新旧代码混用时执行。

## 安装

> 目标环境：Windows 11 · ComfyUI 0.30.x · Python 3.10+。硬依赖只有 `requests`（视觉分析另需 Pillow/numpy，ComfyUI venv 自带），**不需要 torch / CUDA**，CPU 环境可加载全部节点。

```bash
cd E:\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI\custom_nodes
git clone https://github.com/Liuxd-1230/ComfyUI-AI-Prompt-Studio.git
# 重启 ComfyUI；无需安装任何大依赖（requests 一般已存在）
# 可选：PDF/DOCX 附件本地文本提取（0.2.1）——不装则此类附件在无原生文件支持时明确报错
pip install "pypdf>=4.0" "python-docx>=1.1"
```

卸载：删除 `custom_nodes/ComfyUI-AI-Prompt-Studio` 目录即可（不修改 ComfyUI 核心，无残留配置以外的写入）。

## 快速开始

1. 启动 ComfyUI，打开 **Settings（Ctrl+,）** → **AI Prompt Studio**，点击“打开 AI Prompt Studio 设置工作台”。
2. 新建档案，选择 provider、API 根地址和模型，保存后填写 API Key（只保存在本机 `user/ai_prompt_studio/secrets.json`）。先点“测试连接”，再点“重新探测”。
3. “重新探测”会明确提示并发送最小请求，消耗少量 token；完成后检查 Chat/Responses/JSON/工具/图片/文件勾选与失败详情。
4. 在节点图中放置 **AI Model Profile**，直接从“档案名称 [ID]”和该档案的模型目录下拉选择。
5. 图像提示词放置 **Image Prompt Studio**，H3 放置 **MiniMax H3 Prompt Studio**。连接 `AI_PROFILE`，第一次填完整要求；成功后只填本轮修改意见。格式异常或硬规则失败时节点只自动修复一次。
6. H3：把 `prompt`（STRING）接到 H3 生成节点；图像模型：把 `positive` / `negative` 接到采样链路。

示例工作流见 [`examples/`](examples/)：
- `h3_full_chain.json` — H3 全链路（Profile → H3 Prompt Studio → STRING）
- `anima_full_chain.json` — ANIMA 全链路（Profile → Storyboard → Select → Prompt Studio）
- `aps_usage_showcase.json` — Z-Image、Qwen 图片引用和 LLM 生成后卸载

示例均不含密钥。

完整的公开模式、35 条类型兼容端口连接、测试提示词、效果边界与“基元”档案实跑结果见
[提示词边界与工作流全连接验收](docs/testing/提示词边界与工作流全连接验收.md)；机器可读目录为
[`examples/acceptance/prompt_matrix.json`](examples/acceptance/prompt_matrix.json)。

## 节点说明

完整的每个输入/输出端口、连接方向和类型说明见 [节点端口参考](docs/node-reference-zh.md)；所有枚举模式、期待输入与成品示例见 [模式与提示词示例](docs/prompt-mode-examples-zh.md)。这些内容也同步到 ComfyUI 节点内的中文帮助页。

| 节点 | 功能 | 关键输入 | 关键输出 |
|---|---|---|---|
| **AI Model Profile** | 选择档案、覆盖模型/协议/联网/卸载策略 | profile / protocol / reasoning | `AI_PROFILE` |
| **LLM Generate / Chat** | 通用对话/生成（流式、推理、联网、会话） | `AI_PROFILE`、prompt | `LLM_RESULT`、`CHAT_SESSION` |
| **Reference Analyzer** | 文本/图片参考分析（11 种模式） | `AI_PROFILE`、text、images | `REFERENCE_ANALYSIS`、`CHARACTER_CANDIDATE`、`REFERENCE_MANIFEST`、可见 `caption` 锚点摘要、IMAGE 透传 |
| **Character Bible** | 合并人物特征、锁定、冲突报告 | `CHARACTER_CANDIDATE`、`existing_bible` | `CHARACTER_BIBLE`、人物提示片段 |
| **Storyboard Builder** | 剧情 → 结构化分镜（LLM）；收敛场景/时长/ID并生成连续性报告；格式失败默认重试一次 | `AI_PROFILE`、story_text、CharacterBook、retry_on_invalid | `STORYBOARD`、continuity |
| **Storyboard Select / Batch** | 场景/镜头/区间/全部选择（不调模型）；输出可直接接下游的完整镜头文本 | `STORYBOARD` | 单项、容器及真实 ComfyUI `STORY_ITEMS` 列表输出 |
| **Image Prompt Studio** | 持续维护完整图像提示词，自动 CREATE/REFINE | `AI_PROFILE`、text、target | positive、negative、`prompt_session`、validation |
| **图片引用提示词（输入 @）** | 图片连接 → 模型引用语法与资产清单 | prompt、target、image_1～3 | prompt、`REFERENCE_MANIFEST`、references、count |
| **MiniMax H3 Prompt Studio** | 持续维护完整官方 H3 文本 | `AI_PROFILE`、text、mode、duration、媒体 | prompt、`prompt_session`、`REFERENCE_MANIFEST`、validation |
| **Local Runtime Control** | 本地模型加载/卸载/状态 | `AI_PROFILE`、action、backend | profile、status、loaded、op |
| **Unload LM Studio Model** | LLM 后卸载 LM Studio，并把提示词透传给后续生成 | prompt、model、url | prompt、result(JSON)、status(文本) |

节点之间用自定义数据类型（`AI_PROFILE` / `STORYBOARD` / `PROMPT_SESSION` 等）传递结构化对象，工作流可读可保存。

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
- 当前 Studio 统一输出 `natural_language` 成品，不再暴露旧 `tags` / `hybrid` operation 组合。
- **语言要求**：最终视觉正文使用英文；Studio 的系统提示与提交前检查共同保证这一点。角色名、专有名词、引用标签与引号内画面文字可以保留原语言。
- **Safety 标签**：Studio 不固定注入 `safe`，也不默认增加 `sensitive/nsfw/explicit`；当前公开节点没有独立 safety 下拉。官方模型卡的推荐前缀与用户内容意图由最终目标服务自行执行。

## MiniMax H3（官方手册规则）

- **四模式（T2VA/I2VA/FL2VA/L2VA）**：首行对齐指令（I2VA 首帧锚定 / FL2VA 首尾帧路径、默认单镜头 / L2VA 尾帧收敛）+ 空行 + 三字段 `integrated_multimodal_description` / `overall_soundscape` / `non_diegetic_music`。
- **Ref2VA**（旧工作流 `R2V` 自动迁移）：六段 `subject_definitions` / `summary`（`[任务类型]` 前缀）/ `retention_analysis` / `detailed_description` / `overall_soundscape` / `non_diegetic_music`；图片≤9、视频≤3、音频≤3、混合≤12，视频总时长≤15 秒、音频总时长≤15 秒。
- 镜头 `[Shot 1]` 无时间戳，后续 `[Shot N] At MM:SS.mmm, ...` 严格递增；对白 `<d>[Language] ...</d>` 逐字保留原语言；说话人稳定 `(S1)` `(S2)`。
- 首行指令、时间戳和标签编号由 **Python 确定性渲染**；`validation` 仍会检查模型产生的语义、引用、媒体边界与声音字段，失败不会伪装成通过。
- 格式依据：[MiniMax-H3 官方提示词指南](https://github.com/MiniMax-AI/MiniMax-H3/tree/main/skills/h3-prompt-writing)；官方仓库仅作研究来源，本项目运行时规则集中在 Model Core，实现差异与固定提交见 `docs/research/`。

## 安全模型

- **密钥不进工作流 JSON / 节点图 / git / 日志**：`AI_PROFILE` 节点载荷只含档案元数据（`node_payload()` 剔除 `api_key_ref`）；密钥只在设置工作台填写，存于 ComfyUI 用户目录的独立 `secrets.json`，接口一律脱敏返回。
- 日志对密钥脱敏（masked logs）。
- 不改 ComfyUI 核心：只注册节点、`WEB_DIRECTORY` 前端资源与 `/api/ai_prompt_studio/*` 路由（自动带 `/api` 前缀副本）。
- 不安装 CUDA/Torch 等大依赖；不把 Transformers 模型加载进 ComfyUI 进程。

## 兼容性

- **ComfyUI 0.30.x**：已隔离 `comfy.logging → comfy.internal_logging` 破坏性变更（本扩展不 import 核心日志）。
- **本地运行时**：Ollama / llama.cpp / LM Studio（v1 官方推荐；模型标识按官方 `key` 字段，`id` 仅存在于已加载实例 `loaded_instances` 条目；未达 v1 的旧版自动降级为 v0 只读状态查询）。
- **无 GPU 环境**：提示词相关功能只依赖 `requests`，可离线加载；联网功能（网关/探测）在无网络时明确报错，不伪装。
- **第三方共存**：MiniMax H3 采样三件套（Turbo / DualClock / TE-Speed）——H3 Prompt Studio 只输出 STRING，不重复采样后端；ANIMA_BOOSTER 未安装时软检测提示，不硬依赖。
- 详见 `docs/compatibility.md`。

## 后端路由（设置工作台）

`/api/ai_prompt_studio/status` · `profiles`（GET/POST）· `profiles/{id}`（GET/PUT/DELETE）· `profiles/{id}/api_key`（POST/DELETE）· `profiles/{id}/probe` · `profiles/{id}/test` · `capabilities` · `log` · `settings`（GET/POST）· `runtime` · `supplements`（GET/POST/PUT/DELETE/enabled）。ComfyUI 会自动注册 `/api` 前缀副本。

## 开发与测试

```bash
powershell -ExecutionPolicy Bypass -File scripts/verify_prompt_contracts.ps1
```

- PH9 单一入口依次执行全量 pytest、所有生产层 Python 编译、逐个 `web/*.js` 语法检查和 `git diff --check`；测试覆盖加载器语义、aiohttp 路由回环、三后端 mock、H3/ANIMA 正反用例、示例工作流接口契约、全公开模式/端口目录和主链路回归。发布门见 `docs/prompt-architecture/ph9-prompt-contract-regression.md`，实跑矩阵见 `docs/testing/提示词边界与工作流全连接验收.md`。
- 架构与决策：`docs/decisions.md`、`docs/adr/`、`docs/compatibility.md`。
- P0-P4 历史架构与当前单一路径决策见 `docs/prompt-architecture/` 和 `docs/adr/`。Studio 只做可证明的确定性硬检查，不调用 Semantic Critic，也不做隐藏的创意自动修复。四个目标模型的一手证据和本地差异见 `docs/prompt-sources/`。
- 2026-08-11 的真实 ComfyUI/LM Studio 提示词验收记录见 `docs/prompt-architecture/p4.1-real-acceptance-2026-08-11.md`；记录明确区分已实跑项、自动化故障注入项和仍未能由当前模型现场诱发的损坏协议响应。

## 许可与来源

MIT License（见 [LICENSE](LICENSE)）。目标提示词规范只采用模型作者的一手资料；固定版本、访问日期和本地差异见 `docs/prompt-architecture/official-source-ledger.md`。参考实现的边界见 `docs/licenses-and-sources.md`；不复制 ANIMA_BOOSTER / ComfyUI-Prompt-Assistant 内部实现。

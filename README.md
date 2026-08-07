# ComfyUI AI Prompt Studio

面向 ComfyUI 的 LLM 提示词工作流扩展（AI 提示词工作室）。把「剧情构思 → 人物档案 → 分镜 → 目标模型提示词」整条链路搬进 ComfyUI 节点图，覆盖 **ANIMA** 与 **MiniMax H3** 两类生成式视频模型的官方提示词规范。

9 个节点，统一分类 **`AI Prompt Studio`**，类名统一 **`APS_`** 前缀。

---

## 功能总览

- **统一 LLM 网关**：DeepSeek Responses API / Chat Completions（含原生联网搜索、推理、流式）；任意 OpenAI 兼容端点；本地运行时（Ollama / llama.cpp / LM Studio）。
- **AI Model Profile**：命名服务档案 + 能力探测 + 密钥安全存放（密钥永远不进工作流 JSON）。
- **Reference Analyzer**：文本锚点 / 图片特征反推，多图共识与冲突，人物来源证据，输出参考资产清单。
- **Character Bible**：人物稳定身份（stable / variable / current / uncertain），5 种合并策略，字段锁定，冲突报告，H3 说话人 ID。
- **Storyboard Builder / Select**：模型无关的剧情分镜（场景 / 镜头 / 节拍），选择与批处理，不写目标模型格式。
- **Model Prompt Composer**：7 种操作 × 7 类目标（ANIMA Base/Aesthetic/Turbo 等），正负提示词拆分，官方档案，Skill 系统（YAML）。
- **MiniMax H3 Prompt Director**：T2VA / I2VA / FL2VA / L2VA / R2V 五模式官方格式，LLM 产出结构化计划 + Python 确定性渲染 + 规则校验 + 修复循环，输出 STRING 直连核心 H3 节点。
- **Local Runtime Control**：Ollama / llama.cpp / LM Studio 的加载、卸载、状态查询。
- **设置工作台**：ComfyUI 内嵌面板（设置按钮打开），档案管理、密钥（脱敏）、API 测试、能力状态、运行时状态、提示词预览、验证报告。

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

1. 启动 ComfyUI，点顶部菜单 **AI Prompt Studio** 打开设置工作台。
2. 新建档案（如 `deepseek`），选择 provider，填写 API Key（只保存在你本机 `user/<pkg>/config.json`，界面只回显脱敏值），点「测试连接」。
3. 在节点图中放置 **AI Model Profile** → 档案 ID 留空（用默认档案）或填档案名。
4. 放置 **MiniMax H3 Prompt Director**（或 **Model Prompt Composer**），把 `AI_PROFILE` 连上，填剧情文本，运行。
5. H3：把 `prompt`（STRING）接到 ComfyUI 核心 H3 节点的 prompt 输入；ANIMA：把 `positive` / `negative` 接到采样链路。

示例工作流见 [`examples/`](examples/)：
- `h3_full_chain.json` — H3 全链路（Profile → H3 Director → STRING）
- `anima_full_chain.json` — ANIMA 全链路（Profile → Storyboard → Select → Composer）

两个示例均不含密钥，可在设置工作台配好档案后直接加载使用。

## 节点说明

| 节点 | 功能 | 关键输入 | 关键输出 |
|---|---|---|---|
| **AI Model Profile** | 选择档案、覆盖模型/协议/联网/卸载策略 | profile / protocol / reasoning | `AI_PROFILE` |
| **LLM Generate / Chat** | 通用对话/生成（流式、推理、联网、会话） | `AI_PROFILE`、prompt | `LLM_RESULT`、`CHAT_SESSION` |
| **Reference Analyzer** | 文本/图片参考分析（11 种模式） | `AI_PROFILE`、text、images | `REFERENCE_ANALYSIS`、`CHARACTER_CANDIDATE`、`REFERENCE_MANIFEST`、IMAGE 透传 |
| **Character Bible** | 合并人物特征、锁定、冲突报告 | `CHARACTER_CANDIDATE`、`existing_bible` | `CHARACTER_BIBLE`、人物提示片段 |
| **Storyboard Builder** | 剧情 → 结构化分镜（LLM） | `AI_PROFILE`、story_text | `STORYBOARD` |
| **Storyboard Select / Batch** | 场景/镜头/区间/全部选择（不调模型） | `STORYBOARD` | `STORY_ITEM`、`STORY_ITEM_LIST`、batch |
| **Model Prompt Composer** | 文本/分镜/人物 → 目标模型提示词 | `AI_PROFILE`、text、target、operation | positive、negative、`PROMPT_PLAN`、`GENERATION_PROFILE` |
| **MiniMax H3 Prompt Director** | H3 五模式提示词生成/改写/转换/审计/修复 | `AI_PROFILE`、text、mode、operation | prompt(STRING)、`H3_PROMPT_PLAN`、validation |
| **Local Runtime Control** | 本地模型加载/卸载/状态 | `AI_PROFILE`、action、backend | profile、status、loaded、op |

节点之间用自定义数据类型（`AI_PROFILE` / `STORYBOARD` / `H3_PROMPT_PLAN` 等）传递结构化对象，工作流可读可保存。

## ANIMA 提示词（官方档案）

- **Base**：前缀 `masterpiece, best quality, score_7, `（0.2.1 起 **不再强制注入 `safe`**，见下方 Safety 标签）+ 官方负面（`worst quality, low quality, score_1..3, artist name, blurry, jpeg artifacts, chromatic aberration`），建议 30-50 步 / CFG 4-6。
- **Aesthetic**：官方建议正负提示词都不用 `score_*` 标签，30-50 步 / CFG 4.5。
- **Turbo**：官方示例前缀 + **CFG 1 / 8-12 步**。
- 语法：小写标签、空格分隔（`score_*` 是唯一带下划线的标签）、`@artist` 艺术家前缀、标签分段排序（quality/meta/year/safety → count → artist → general）、LoRA 触发词原样保留追加。
- 支持 `tags` / `natural_language` / `hybrid` 三模式。
- **Safety 标签（0.2.1）**：节点参数 `safety_tag` ∈ `none / safe / sensitive / nsfw / explicit`，**默认 `none` = 不注入任何 Safety 标签**（Composer 不在用户未要求时给提示词增加内容语义，也不做内容审查——审查留给模型服务端）。官方 safety 标签全集为 `safe / sensitive / nsfw / explicit`，`safe` 只是官方示例默认而非强制项；Composer 只按用户明确选择渲染。旧参数 `content_tier`（safe/sensitive）自动迁移。

## MiniMax H3（官方手册规则）

- **四模式（T2VA/I2VA/FL2VA/L2VA）**：首行对齐指令（I2VA 首帧锚定 / FL2VA 首尾帧路径、默认单镜头 / L2VA 尾帧收敛）+ 空行 + 三字段 `integrated_multimodal_description` / `overall_soundscape` / `non_diegetic_music`。
- **R2V**：六段 `subject_definitions` / `summary`（`[任务类型]` 前缀）/ `retention_analysis`（保留标记）/ `detailed_description`（风格开场在 `[Shot 1]` 前）/ `overall_soundscape` / `non_diegetic_music`。
- 镜头 `[Shot 1]` 无时间戳，后续 `[Shot N] At MM:SS.mmm, ...` 严格递增；对白 `<d>[Language] ...</d>` 逐字保留原语言；说话人稳定 `(S1)` `(S2)`。
- 首行指令、时间戳、标签编号由 **Python 确定性渲染**，格式不可能跑偏；`validation` 输出结构错误 + 内容警告，`repair` 一次回灌修复。
- 格式依据：官方手册（`docs/sources/`），详见 `docs/research.md` §5。

## 安全模型

- **密钥不进工作流 JSON / 节点图 / git / 日志**：`AI_PROFILE` 节点载荷只含档案元数据（`node_payload()` 剔除 `api_key_ref`）；密钥只在设置工作台填写，存于 ComfyUI 用户目录 `config.json`（`folder_paths.user_directory`），接口一律脱敏返回。
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

- 测试 430+：加载器语义复现（`spec_from_file_location`）、真实 aiohttp `RouteTableDef` 路由回环、三后端 mock、H3/ANIMA 全部官方格式规则正反用例、示例工作流可加载校验、8 条主链路回归（`tests/test_main_flows.py`）。
- 架构与决策：`docs/decisions.md`（D1–D24）、`docs/research.md`（含来源与日期）、`docs/adr/`、`docs/compatibility.md`。

## 许可与来源

MIT License（见 [LICENSE](LICENSE)）。提示词格式规范来自 ANIMA 官方模型卡（CircleStone Labs / Civitai 2458426）与 MiniMax H3 官方手册（用户提供，存档于 `docs/sources/`，不入 git）。参考实现的边界见 `docs/licenses-and-sources.md`；不复制 ANIMA_BOOSTER / ComfyUI-Prompt-Assistant 内部实现。

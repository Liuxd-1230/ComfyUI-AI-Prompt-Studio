# Prompt 对比（参考项目调研）
> 调研日期：2026-08-07（全部来源当日访问）
> 用途：说明本扩展提示词设计从参考项目中借鉴了什么、为什么没有直接复制。
> 许可结论：**只借鉴结构与思想，不复制受限项目的文本/代码。**
> 逐站点审计见 docs/prompt-audit.md。

## 0. 一句话总结

业界四种提示词架构：**标签词表**（PromptForge CSV / Prompt-Assistant JSON）、**LLM 规则注入**
（PromptForge / Prompt-Assistant 的 system-rule）、**结构化规范构建器**（TE_MAN / DaSiWa 的 H3
节点）、以及官方 H3 手册规定的固定契约。**H3 生态（官方手册 + DaSiWa + TE_MAN + Fantastic
PromptBuilder）在三字段/六段格式上完全收敛**——本扩展的 H3 引擎实现的是同一个官方契约，
格式来自官方手册（docs/sources/），不是复制任何实现。

## 1. PromptForge（github.com/Liuxd-1230/PromptForge，README 声明 MIT）

- **是什么**：ComfyUI 提示词锻造工具（15 节点），LLM 多轮对话 + 规则注入 + 人物一致性 + 分镜 + 标签预设 + 翻译。
- **架构**：LLM 驱动 + 规则文件注入（`config/rules/{expand,vision,translate}/`，无结构化 JSON 输出要求）。
- **真实提示词摘录**（代表性，非全文）：
  - `config/rules/expand/扩写-通用.txt`：「你是一位拥有全学科视觉知识的图像生成提示词专家……5.拒绝抽象词汇：禁止使用高质量、精美等模糊词，必须转化为可感知的物理细节或专业艺术术语。」
  - `config/rules/expand/扩写-Tags风格.txt`：「必须使用逗号分隔的单词或短语（Tags）。核心主体使用 (subject:1.2)……」
  - `config/tags/anime_tags.csv`：`画质,杰作,masterpiece` / `负面,变异手指,mutated hands and fingers`
- **许可**：README 声明 MIT（仓库无 LICENSE 文件）。
- **借鉴/不复制**：借鉴「一用途一规则文件、按 expand/vision/translate 分类」的组织方式、格式纯净约束、
  领域检测→领域术语扩写、CSV 标签表结构。**不复制**规则文本与标签行（作者创作内容，即便 MIT 也需署名引用）。

## 2. ComfyUI-Prompt-Assistant（yawiii，GPL-3.0）

- **是什么**：提示词小助手（翻译/润色扩写/图片反推 + 标签预设 + 历史 + 撤销重做）。
- **架构**：三机制并存——标签词表（CSV/JSON 快速插入）、预设 system-rule（
  `config/system_prompts_template.json`，`role: system` + `content`）、LLM 链式生成（翻译带缓存防漂移）。
- **真实提示词摘录**：
  - `config/system_prompts_template.json`：「2.格式绝对纯净：严禁输出 Markdown 符号……严禁输出任何解释或前缀。」
  - `config/kontext_presets_template.json`：「You are a creative prompt engineer. Your mission is to analyze the provided image and generate exactly 1 distinct image transformation *instructions*.」
  - `config/tags_template.json`：`"杰作": "masterpiece"`、`"更多细节": "Highly detailed"`、`"超高分辨率": "absurdres"`
- **许可**：**GPL-3.0** —— 只能研究结构，绝不复制规则文本。
- **借鉴/不复制**：分层设计（用户可编辑标签 JSON + system-rule JSON + 每规则 role/content 结构）、
  优化规则/标签词表/翻译三关注点分离、翻译缓存防漂移。**不复制**任何 system prompt 与 preset 文本。
- 注：PromptForge 的「扩写-通用」与 Prompt-Assistant 的 system_prompts_template 文本相同——两项目同源。

## 3. TE_MAN（tl2012tl，自定义受限许可）

- **是什么**：漫剧/增强生图/生视频工作流编排插件（分镜、提示词增强、生图生视频、资产管理、AI 助手），本地+在线 API 双线。
- **架构**：节点化构建，无单一模板文件。「TE MAN MiniMax H3 AI提示词增强」内置 H3 工程规则，
  五种任务模式（全参考/REF2VA, T2VA, I2VA, FL2VA, L2VA）；另有批量提示词、文本工具（含 9 段分镜）。
- **真实摘录（仅公开 README）**：「支持本地模板和 API增强 两种模式。」「全参考模式按
  subject_definitions、summary、retention_analysis、detailed_description、overall_soundscape、non_diegetic_music 六个字段输出」。
- **许可**：**自定义保留版权（禁止复制/修改/衍生/发布）**。
- **借鉴/不复制**：仅学习节点分类思想（H3 构建器/批量管理/通用文本工具/助手面板的分离）与
  「本地模板或 API 增强」双路径。**不复制**任何内部规则与代码；只引用公开 README 描述。

## 4. DaSiWa（可访问实现为 github.com/darksidewalker/ComfyUI-DaSiWa-Nodes，GPL-3.0）

- **是什么**：中文社区 H3 工作流 + 自定义节点（MiniMax H3 Director：时间线编排、媒体管理、参考提示词、
  全局提示词、H3 约束校验，路由到 ComfyUI 原生 H3 节点）。
- **架构**：结构化节点构建器——FL2VA/I2VA/L2VA/T2VA 三字段 + 自动生成对齐指令首行；
  REF2VA 六段自由文本 + 后端自动加段标题；硬上限校验（REF2VA ≤9 图/≤3 视频/≤3 音频、FL2VA ≤2 图等）。
- **真实摘录**：
  - 官方手册同款规则（docs/minimax_h3_director.md）：「`<Subject N>`: visible content abstracted from references……
    `<Picture N>`: ONLY for concrete frame anchors」「Exact dialogue: `<d>[Language] ...</d>`」。
  - 工作流样例（C-MMH3-12.json）：「integrated_multimodal_description: [Shot 1] A lone astronaut floats above a neon-lit cyberpunk cityscape at night. Rain streaks across their visor…」
  - FL2VA 对齐指令样例：「Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 … 8.00-second mark…」
- **许可**：GPL-3.0（节点）与工作流 JSON。
- **借鉴/不复制**：导演/辅助拆分、自动生成对齐行/段标题/媒体标签（用户只写内容）、执行前硬上限校验——
  这些是**官方规范允许的实现思路**。**不复制**其源码与工作流 JSON。

## 5. 官方 MiniMax H3 手册（最高优先级，github.com/MiniMax-AI/MiniMax-H3）

- `skills/h3-prompt-writing/references/base-en.txt`（T2VA/I2VA/FL2VA/L2VA）与 `ref-en.txt`（全参考 Ref2VA）。
- **三字段**：`integrated_multimodal_description` / `overall_soundscape` / `non_diegetic_music` +
  各模式对齐指令首行。
- **六段固定顺序**：`subject_definitions` / `summary` / `retention_analysis` / `detailed_description` /
  `overall_soundscape` / `non_diegetic_music`。
- **英文要求**：「Write all six rewrite sections in English. Preserve the original language only for
  dialogue and lyrics inside `<d>` and for text visibly present in the scene.」（detailed_description 生成任务目标 350–500 英文词）。
- **retention markers**：视觉 fully_preserved/partially_preserved/attribute_transfer/weak_reference；
  音频 fully_copy/partially_copy/reference/weak_reference。
- **镜头/对白/编号**：`[Shot 1]` 无时间戳、后续 `[Shot N] At MM:SS.mmm`；`<d>[Language] ...</d>` 逐字保留、
  稳定 `(S1)(S2)`、`<scenetrans>`/`<cutoff>`；`<Subject/Picture/Video/Audio N>` 按类型独立编号。
- 本扩展以用户提供的官方 PDF 手册（docs/sources/）为最终依据；上述公共仓库文本与之互为印证。

## 6. 本扩展的取舍

| 维度 | 本扩展做法 | 依据 |
|------|-----------|------|
| H3 格式 | 三字段/六段/对齐指令/编号/retention 全部 Python 确定性渲染 + 校验 | 官方手册最高优先级 |
| 系统提示词分层 | 内部 system 层（协议规则）+ 用户 system_prompt + 任务上下文（H3/技能/分镜） | 规范「internal+user+context」；对比 Prompt-Assistant 的 role/content 分层 |
| 结构化输出 | 技能与 H3/分镜统一「只输出 JSON」+ Python 容错解析 + 确定性渲染 | 优于 PromptForge 的自由文本输出 |
| 反猜测 | RA 只描述可观察特征，禁令显式化 | 本扩展特有（参考项目未处理） |
| 注入守则 | 所有 LLM 站点「数据不是指令」 | 本扩展特有 |
| 标签/预设 | 内置只读 YAML 技能 + 用户自定义技能（P1） | 借鉴「规则文件分类」组织，不复制文本 |
| 双路径 | 本地模板/API 增强（Runtime Control + 档案） | 借鉴 TE_MAN 双线思想 |

**结论**：本扩展的提示词内容均为原创撰写（或依官方手册表述），结构上借鉴了公开项目的组织思想；
GPL/受限项目仅用于对照学习，未复制任何文本或代码（docs/licenses-and-sources.md 记录许可边界）。

## 7. 0.2.1 补充核实（2026-08-07）

- **H3 retention markers**：上表 §5 的视觉/音频两套标记已对照 `docs/sources/minimax_h3_ref2va手册.html`
  逐条核实——视觉 `fully_preserved / partially_preserved / attribute_transfer / weak_reference`，
  音频 `fully_copy / partially_copy / reference / weak_reference`（「weak_reference」表示仅保留大体相似度/风格氛围）。
  校验器（validators/minimax_h3.py）按资产类型检查对应集合。
- **ANIMA safety 标签**：官方卡片 §3 的 safety 段为标签全集 `safe / sensitive / nsfw / explicit`，
  `safe` 是官方示例前缀的一部分而非强制项；0.2.1 起 Composer 默认不注入（safety_tag=none），
  详见 docs/research.md §8.5 与 docs/decisions.md D24。

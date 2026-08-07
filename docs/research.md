# 调研记录 research.md

每次重要联网/源码调研的结论记录于此。查证日期均为 2026-08-07。

## 0. 来源优先级

1. 用户提供的官方手册（MiniMax H3 FL2V / R2V）
2. 当前实际安装的 ComfyUI 源码（E:\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI，v0.30.2）
3. 官方 API 文档
4. 官方 GitHub 仓库
5. 其他来源（社区/二手总结，标注为非官方）

## 1. ComfyUI 版本与接口

- **问题**：用户所称 0.30.2 是否等于实际核心版本号？扩展接口是什么？
- **结论**：确认为 v0.30.2。证据：`comfyui_version.py` `__version__="0.30.2"`；pyproject `version="0.30.2"`；git HEAD detached at tag `v0.30.2`（commit dec5d945 "ComfyUI v0.30.2"）。ComfyUI Desktop 的 `manifest.json` 显示 v0.28.0/v0.29.0 为过时的构建元数据，不代表实际代码。
- **环境**：Python 3.13.12（`ComfyUI/.venv/Scripts/python.exe`）；torch 2.12.1+cu130；numpy 2.4.6；requests 2.34.2；aiohttp 3.14.3；pydantic 2.13.4（v2）；venv **无 pytest**（系统 Python 3.13.11 有 pytest 9.1.1）。前端包 `comfyui_frontend_package==1.47.12`。
- **扩展接口（源码确认，server.py / nodes.py）**：
  - 自定义节点：`NODE_CLASS_MAPPINGS` + `NODE_DISPLAY_NAME_MAPPINGS` + `WEB_DIRECTORY`（`nodes.py:2245-2273` 收集，前端资源挂在 `/extensions/<node_name>/`）。V1 API 在 0.30.x 仍受支持（V3 schema 为可选迁移，见 docs.comfy.org/custom-nodes/v3_migration）。
  - 后端路由：`from server import PromptServer; PromptServer.instance.routes`（aiohttp `web.RouteTableDef`，`server.py:262-263`）；`add_routes()`（`server.py:1220`）会给每个非静态路由自动注册 `/api` 前缀副本。
  - 前端扩展：`app.registerExtension({name, settings, nodes, ...})`；`app.extensionManager.setting.get/set(id, value)`。
  - **0.30.0 破坏性变更（v0.30.0 release notes / ComfyUI 官方仓库）**：`comfy/logging.py` 重命名为 `comfy/internal_logging.py`——自定义节点不得 `from comfy.logging import ...`。其余为无关 bugfix。v0.30.1/v0.30.2 无 changelog 正文。
- **来源**：ComfyUI 源码（本机）；https://github.com/comfyanonymous/ComfyUI/releases.atom ；https://docs.comfy.org/custom-nodes/overview
- **对实现的影响**：用 V1 API；不 import `comfy.logging`；路由挂 `PromptServer.instance.routes`；前端走 `WEB_DIRECTORY` + `app.registerExtension`。

## 2. DeepSeek API

- **问题**：`deepseek-v4-flash` 是否是真实模型名？Responses / Chat Completions / 联网搜索 / 错误格式各是什么？
- **结论**：
  - **模型名**：`deepseek-v4-flash` 与 `deepseek-v4-pro` 是当前官方页面上唯二的模型 id；**`deepseek-v4-flash` 可部署**，文档称「The deepseek-v4-flash model has been updated to DeepSeek-V4-Flash-0731. The calling method remains unchanged — simply use deepseek-v4-flash」。`deepseek-chat` / `deepseek-reasoner` 未出现在当前任何官方页面；无后缀的 `deepseek-v4` 不是合法 id。
  - **价格/规格**（pricing 页）：输入 $0.14/M（cache-miss，flash），输出 $0.28/M；上下文 1M，最大输出 384K；flash 并发 2500。两者支持 thinking（默认）与非 thinking、JSON 输出、工具调用。**Responses API 目前仅 flash 支持**（pro 计划 2026 年 8 月初支持）。
  - **Responses API**：`POST /responses`，base `https://api.deepseek.com`（OpenAI SDK `client.responses.create` 可用）。请求体：`model`、`input`（字符串或 item 列表：message/function_call/function_call_output/reasoning/web_search_call）、`instructions`、`stream`、`tools`（function / **web_search 原生工具**，其他类型忽略）、`tool_choice`（none/auto/required 或 `{"type":"function","name":...}` / `{"type":"web_search"}` / `{"type":"web_search_2025_08_26"}`）、`reasoning`（effort；summary 接受但不生成）、`max_output_tokens`、`user`。`store` 恒为 false；不支持参数被静默忽略；上下文溢出返回 400。
  - **Responses 流式事件**：`response.created` / `.in_progress` / `response.output_item.added|.done` / `response.content_part.added|.done` / `response.reasoning_text.delta|.done` / `response.output_text.delta|.done` / `response.function_call_arguments.delta|.done` / `response.web_search_call.in_progress|.searching|.completed`；终态 `response.completed` / `.incomplete` / `.failed`。**无 `data: [DONE]`**（与 chat 流不同）。
  - **Chat Completions**：`POST /chat/completions`，base `https://api.deepseek.com`（当前文档未提 `/v1`；另有 `https://api.deepseek.com/anthropic`）。请求体：`messages`、`model`、`thinking`（`type: enabled|disabled`、`reasoning_effort: low|high|max`，medium/xhigh 映射为 high）、`max_tokens`、`response_format`（text/json_object）、`stop`、`stream`、`stream_options.include_usage`、`temperature`(<=2)、`tools`（function 调用，max 128）、`tool_choice`。流以 `data: [DONE]` 结束。usage 含 `prompt_cache_hit/miss_tokens`、`completion_tokens_details.reasoning_tokens`。
  - **原生联网搜索**：**仅存在于 Responses API**——`tools` 加 `{"type":"web_search"}` 或 `{"type":"web_search_2025_08_26"}`，服务端执行；`search_context_size`/`user_location` 被忽略。Chat Completions 无 web_search 工具文档。无独立 web search 指南页（sitemap 无 `/guides/web_search`）。
  - **错误**：官方 error_codes 页只文档化 HTTP 状态码：400 Invalid Format、401 Authentication Fails、402 Insufficient Balance、**403（推测，未文档化）**、422 Invalid Parameters、429 Rate Limit、500 Server Error、503 Server Overloaded。**JSON 错误体结构未公开**（不要依赖 `error.code` 字段；按状态码判断；`error.message` 尽力读取）。
- **来源**：https://api-docs.deepseek.com/quick_start/pricing ；https://api-docs.deepseek.com/guides/responses_api（en/zh-cn）；https://api-docs.deepseek.com/api/create-response ；https://api-docs.deepseek.com/api/create-chat-completion ；https://api-docs.deepseek.com/api/list-models ；https://api-docs.deepseek.com/quick_start/error_codes ；https://api-docs.deepseek.com/sitemap.xml
- **冲突记录**：官方文档在「base URL 是否带 /v1」与「错误 JSON 结构」上无明确说明；按「无 /v1、按状态码」执行，并兼容 `/v1` 前缀（OpenAI SDK 默认路径）。
- **对实现的影响**：默认模型字面量 `deepseek-v4-flash`；联网搜索只走 Responses；能力探测用 `GET /models`（list-models 仅返回两模型）；错误归一化以状态码为主。
- **实现基线（2026-08-07）**：能力按**具体模型**判定，不再 provider==deepseek 一刀切——`deepseek-v4-flash` → responses=True / native_web_search=True（仅 Responses 路径）/ vision=False / files=False；`deepseek-v4-pro` → responses=False（Responses 计划 2026-08 初上线，当前不可用）/ web_search=False；未知 DeepSeek 模型 → 保守（responses 未知，网关按静态表 `deepseek_known_responses()` 兜底，未知模型走 chat_completions）。Chat `response_format` 仅 json_object（json_schema 未文档化）→ structured_output 走提示词约束+解析+修复，不承诺严格 schema。

## 3. ANIMA 提示词

- **问题**：ANIMA Base / Aesthetic / Turbo 的官方提示词与采样建议。
- **结论**：官方正源为 **CircleStone Labs（与 Comfy Org 合作）** 的 2B text-to-image 模型（基于 NVIDIA Cosmos），Civitai 模型卡 2458426；HF `circlestone-labs/Anima` 为官方关联仓库（本次直接抓取超时，标记为「官方卡片关联、未独立复核」）。**`BlackSnowSkill/ANIMA_BOOSTER` README 无任何提示词指导**（只有 JIT/SageAttention/TeaCache 安装优化）。
  - **版本**：Base（base-v1.0，完全训练的基础模型，可训 LoRA）、Aesthetic（v1.0/v1.1，一致性更高/更高默认美术风格）、Turbo（v1.0，蒸馏，**CFG 1、8-12 步**）。Base/Aesthetic：30-50 步、CFG 4-6（Aesthetic 可 CFG 3）。官方建议起点：Turbo。
  - **正面前缀（官方）**：`masterpiece, best quality, score_7, safe, `
  - **默认负面（官方）**：`worst quality, low quality, score_1, score_2, score_3, artist name, blurry, jpeg artifacts, chromatic aberration`
  - **score 差异**：Base 推荐 score 标签（前缀 `score_7`、负面 `score_1..3`）；**Aesthetic 官方明确「建议正负提示词都不用 score_* 标签」**（quality 标签可选，`masterpiece, best quality,` 可保留）；**Turbo 官方未给 score 指导**（社区说法不可靠）。
  - **语法**：小写标签；标签间用空格而非下划线（**score 标签是唯一带下划线的标签**）；优先 Gelbooru 变体；权重需高于 SDXL 值（如 `(chibi:2)`）；品质词可用人类式（masterpiece/best quality/good quality/normal quality/low quality/worst quality）或 PonyV7 式（score_9..score_1）。
  - **标签顺序**：`[quality/meta/year/safety] [1girl/1boy/1other...] [character] [series] [artist] [general tags]`（段内任意）。
  - **时间/元/安全**：`year 2025` / `newest/recent/mid/early/old`；meta：`highres, absurdres, anime screenshot, jpeg artifacts, official art`；safety：`safe, sensitive, nsfw, explicit`。
  - **艺术家标签**：必须加 `@` 前缀（如 `@big chungus`），否则效果很弱。
  - **自然语言模式（官方）**：标签与 NL 可任意混排；建议 >=2 句；quality/artist 放句首；先写人物名再描述外貌（多人物尤其）；人物/系列名用标准大写。
  - 模型「不做写实」，文字渲染差。
- **来源**：https://civitai.com/models/2458426 （Anima 官方模型卡）；https://huggingface.co/circlestone-labs/Anima （官方关联，未独立复核）；https://github.com/BlackSnowSkill/ANIMA_BOOSTER （无提示词指导，仅兼容检测）
- **冲突记录**：社区（としあきdiffusion Wiki、note.com 文章）有 Turbo score 用法传言——**非官方，不采用**。
- **对实现的影响**：ANIMA renderer 内置 Base/Aesthetic/Turbo 三套档案：Base 用官方前缀+负面+score；Aesthetic 去 score 标签；Turbo 用官方示例前缀 + CFG 1/8-12 步 GenerationProfile；提供 safe/sensitive 开关、`@artist` 处理、标签分段排序、权重语法、tags/natural/hybrid 三模式。

## 4. 本地运行时接口

- **问题**：Ollama / llama.cpp server / LM Studio 的加载、卸载、查询接口。
- **结论**：
  - **Ollama**：**没有 /api/load 或 /api/unload**。加载 = `POST /api/generate`（空 prompt）或 `POST /api/chat`（空 messages）触发自动加载；卸载 = 同一请求带 `keep_alive: 0`；运行中模型 = `GET /api/ps`；模型信息 = `POST /api/show`；模型列表 = `GET /api/tags`。
  - **llama.cpp server**：`POST /models/load` `{"model":"..."}` → `{"success":true}`；`POST /models/unload` `{"model":"..."}`；`GET /v1/models` 返回**已加载**模型信息（`--alias` 覆盖 id）；`GET /health`；`GET /models` 列可用模型（router 模式）；默认端口 8080。旧 `/load_model` 不在当前 README。
  - **LM Studio**：原生 REST API **v1**（LM Studio >= 0.4.0）：`POST /api/v1/models/load` `{"model":"...","context_length":16384,"flash_attention":true}` → `{type, instance_id, load_time_seconds, status:"loaded"}`；`POST /api/v1/models/unload` `{"instance_id":"..."}`。旧 **v0**（OpenAI 兼容，`http://localhost:1234`，`Bearer $LM_API_TOKEN`）：`GET /api/v0/models`（有 `state` 字段如 `"not-loaded"`），**无 load/unload 端点**。
- **来源**：https://raw.githubusercontent.com/ollama/ollama/main/docs/api.md ；https://docs.ollama.com/api ；https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md ；https://lmstudio.ai/docs/developer/rest/load 、/unload 、/endpoints
- **对实现的影响**：runtime 后端分别实现上述真实端点；LM Studio 走 v1、未达 v0.4.0 时降级为只读状态查询。

## 5. MiniMax H3 官方手册（用户提供，最高优先级）

- **问题**：H3 提示词格式。
- **结论**（已全文阅读 `docs/sources/minimax_h3_FL2V手册.html` 与 `minimax_h3_r2v手册.html`）：
  - **T2VA/I2VA/FL2VA/L2VA 三字段固定**：`integrated_multimodal_description:` / `overall_soundscape:` / `non_diegetic_music:`。
  - **首行对齐指令**（T2VA 无）：I2VA `For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.`；FL2VA `How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot N) aligns with the S.SS-second mark of the target video.`；L2VA `How the reference pictures align with the target video — <Picture 1> (from [Shot N]) aligns with the S.SS-second mark of the target video.`（N=实际末镜，S.SS=有效视频时长精确两位小数；指令后跟一个空行）。
  - **镜头规则**：`[Shot 1]` 无时间戳；后续 `[Shot N] At MM:SS.mmm, ...` 严格递增；标准切换语 the camera cuts to / the shot cuts to / transitions to / changes to / switches to；交叉淡变仅在显式要求时。
  - **相机运动**：类型（Zoom/Push in/Pull out/Pan/Truck/Tilt/Pedestal/Arc/Tracking/Static/Shake/POV/Roll）+ 幅度（small/large amplitude）+ 速度（slow/fast speed），自然英文句。
  - **说话人**：稳定 ID `(S1)` `(S2)`，复合 `(S1,S2)`；首次出现须在 `<d>` 外建立身份；对白 `<d>[Language] ...</d>`，原词/标点逐字保留；画外音用 `says in an off-screen voiceover` 且 `<d>` 后注明闭唇；跨切对白 `scenetrans`；截断 `cutoff`。
  - **画面文字**：英文双引号内保留原文。
  - **soundscape**：1-4 句，不重复对白/唱词/配乐；全静音才用 `N/A`。**non_diegetic_music**：1-3 句，只写乐器/速度/力度，禁抽象情绪词；无则 `N/A`。
  - **R2V 六段固定顺序**：`subject_definitions:` / `summary:` / `retention_analysis:` / `detailed_description:` / `overall_soundscape:` / `non_diegetic_music:`。正文英文；`<d>` 对白/歌词/画面文字保留原语言。
  - **四类标签**：`<Subject N>`（可复用可见内容单元）、`<Picture N>`（作为首/关键/尾帧或构图锚点的参考图）、`<Video N>`（整段视频关系：剪辑/续接/节奏结构）、`<Audio N>`（音频信号）。视频与音频独立编号。
  - **summary 任务前缀**：`[reference generation]` / `[video editing + reference generation + audio reuse]` 等。
  - **retention markers（可见内容）**：`fully_preserved` / `partially_preserved` / `attribute_transfer` / `weak_reference`；**音频**：`fully_copy` / `partially_copy` / `reference` / `weak_reference`。
  - **R2V detailed_description 差异**：风格开场在 `[Shot 1]` 之前（1-2 句）；首现标签须描述特征+位置+动作；说话时 `<Subject N> (Sx)`。
- **来源**：docs/sources/minimax_h3_FL2V手册.html、docs/sources/minimax_h3_r2v手册.html（用户提供，2026-08-04 下载）
- **对实现的影响**：renderer/validator 全部按此实现；首行指令 Python 确定性生成；FL2VA 默认单镜头连续路径。

## 6. 其他事实

- 本机 ComfyUI 已装 MiniMax H3 三件套：ComfyUI-MiniMax-H3-Turbo（LoRA + 4-step sampler）、ComfyUI-MiniMaxH3DualClockSampler、TE-Speed-MiniMaxH3（编译 nodes.pyd）——均为 LoRA/采样器，**prompt 输入在 ComfyUI 核心原生 H3 节点**（STRING）。ANIMA_BOOSTER **未安装**。
- 前端默认端口 8188（comfy/cli_args.py）；模型/输入/输出目录重定向到 `E:\Comfy-Desktop\ComfyUI-Shared`。
- 用户 ComfyUI 前端包 1.47.12；`app.extensionManager.setting` 持久化在服务端 `comfy.settings.json`（app/app_settings.py，user 目录）。

## 7. Batch C/D 补充查证（2026-08-07）

- **函数工具协议结构（OpenAI Responses / Chat Completions 官方）**：
  - Chat：`tools: [{"type":"function","function":{"name","description","parameters"}}]`；续轮 = assistant 消息带 `tool_calls:[{"id","type":"function","function":{"name","arguments"}}]` + 每条工具结果一条 `{"role":"tool","tool_call_id","content"}`。
  - Responses：`tools: [{"type":"function","name","description","parameters"}]`；续轮 = assistant item 带 `output:[{"type":"function_call","call_id","name","arguments"}]` + `{"type":"function_call_output","call_id","output"}` 顶层条目。
  - 工具执行失败 → 错误文本回给模型继续（不抛异常、不伪造）；上限 `MAX_TOOL_ROUNDS=4`（产品决策，不暴露节点 UI）。
- **外部搜索后端契约（自定义 HTTP 优先，本仓库定义）**：`POST {query} → 200 {"results":[{"title","url","snippet"}]}`（兼容 `{"items":[...]}`）；401/402/403/429/5xx/超时/非 JSON/契约不符 → 明确失败，注入离线警告，绝不伪造结果。前端 settings 高级区 `search_url` 字段。
- **llama.cpp 官方 load/unload**：`POST /models/load|unload`，body 为 `{"model": ...}`（README/server 源码确认，非 `{"id": ...}`）。LM Studio v1：`/api/v1/models/load|unload`；v0 只读降级。
- **多图身份判断**：无第三方库；纯函数 `identity_agreement`（stable 特征名与值一致比例）+ 贪心聚类；多主体时只合并最高一致度分组（防跨主体串绑，P0）。
- **视觉/文本 Profile 解耦**：`AIProfile.vision_profile_id` 指向另一档案时视觉用该档案配置与密钥；实现为字段级解耦（不复制密钥引用）。

## 8. 0.2.1 Hardening 补充查证（2026-08-07）

### 8.1 DeepSeek Responses 原生 Structured Output（P0-3）

- **问题**：deepseek-v4-flash 的 Responses API 是否支持 `text.format` json_schema？Chat 是否支持 json_schema？
- **官方结论**：
  - Responses 兼容表：`text — Partially supported. format fully supported`（`json_schema` 一词官方页未出现，但明确委托 OpenAI Responses API reference 作为完整格式定义）。
  - 字段结构（OpenAI 官方参考，DeepSeek 声明兼容）：`{"text": {"format": {"type": "json_schema", "name": "...", "schema": {...}, "strict": true, "description": "..."}}}`。`name` 必填（<=64 字符）；`strict` 可选布尔。
  - Chat Completions：`response_format` 官方只文档化 `{"type":"text"}` / `{"type":"json_object"}`，**无 json_schema**。
- **实现决定**：能力表协议级区分 `structured_output_responses` / `structured_output_chat`（flash: True/False）；Gateway 按当前协议判定是否走原生 schema；Chat 路径继续提示词约束 + JSON parse + 修复。
- **来源**：https://api-docs.deepseek.com/guides/responses_api ；https://api-docs.deepseek.com/api/create-chat-completion ；OpenAI Responses reference（DeepSeek 官方委托定义）。

### 8.2 DeepSeek 附件能力（P0-6）

- **官方结论**：deepseek-v4-flash **不支持图片/文件输入**——`input_image` parts 不报错但被替换为占位文本；`input_file` 未文档化（视为不支持）。vision=False、files=False 为诚实标记。
- **实现决定**：能力 gate 在协议选择前执行；DeepSeek 图片附件明确报错、PDF/DOCX 本地提取文本降级、其他二进制报错；绝不静默伪装发送。

### 8.3 Responses function call 的 call_id（P0-7）

- **官方结论**（OpenAI Responses reference，DeepSeek 声明兼容）：
  - `call_id` 只出现在 function_call 输出项上（非流式 `output[]` 与 `response.output_item.done` 的 `item`）：`{"type":"function_call","call_id":"fc_...","id":"fc_...","name":...,"arguments":...,"status":"completed"}`。
  - 流式 `response.function_call_arguments.delta/.done` 事件**不携带 call_id**，而是 `item_id` + `output_index` + `name` + `arguments`。
- **实现决定**：SSE 解析按 `item_id`（或 output_index）累积参数；call_id 在 function_call 项到达时取权威值；续轮 `function_call_output.call_id` 逐字沿用模型返回 ID，绝不伪造 `call_0`。

### 8.4 LM Studio v1 探测与 unload（P0-8/9）

- **官方结论**（lmstudio.ai/docs/developer/rest，LM Studio >= 0.4.0）：
  - v1 官方推荐；`GET /api/v1/models` 响应顶层为 `{"models": [...]}`（**不是** v0 的 `{"data": [...]}`）；每模型含 `loaded_instances: [{"id": ..., "config": ...}]`。
  - `POST /api/v1/models/load` 请求体 `{"model": ..., "context_length": ..., "flash_attention": ..., "echo_load_config": ...}`；**响应**含 `instance_id`。
  - `POST /api/v1/models/unload` 请求体为 `{"instance_id": ...}`（唯一文档化字段，**不能用 model**）。
  - 版本探测：官方未文档化程序化机制 → v1 优先、失败再试 v0、都失败 unavailable（实现选择）。
- **实现决定**：探测改为 v1 优先；v1 列表解析 `models` 键；load 保存响应 `instance_id`；unload 用 `instance_id`（优先自保存，其次从 `loaded_instances` 列表查）；用户只传 model 也能卸载。

### 8.5 ANIMA safety 标签（0.2.1 补充 P0）

- **官方结论**：官方列出的 safety 标签全集 `safe / sensitive / nsfw / explicit`；`safe` 只是官方示例前缀中的默认，**不代表所有 Prompt 必须带 safe**。
- **实现决定**：节点参数 `safety_tag ∈ none/safe/sensitive/nsfw/explicit`，默认 **none**（不注入任何 Safety 标签）；旧 `content_tier`（safe/sensitive）自动迁移；三种 prompt_mode 统一尊重；Plan 建议的安全标签被忽略（用户参数优先）；Composer 不做内容审查、不自动改等级。Aesthetic/Turbo 只处理 Safety 标签，不重新引入 score 规则。

### 8.6 MiniMax H3 retention markers 复核（P0-16）

- **官方结论**（用户提供 R2V 手册 §4.2）：音频 marker 完整集合 = `fully_copy` / `partially_copy` / `reference` / **`weak_reference`**（"Broad similarity only"）。`weak_reference` 同时是视觉 marker（"Only broad similarity in style/atmosphere retained"）。
- **实现决定**：RETENTION_MARKERS 已含 weak_reference（视觉与音频共用，validator 按资产类型判定）；系统提示词改为分别列 visual/audio marker 集（不再把 weak_reference 只归为视觉）。

# 已知限制 known-limitations.md

本文记录本扩展**已明确不接受或未实现**的能力边界，以及对应的行为约定。
凡与官方文档冲突之处以官方为准；凡此处标注「未实现」的功能不会被伪装为可用。

## 1. 模型 / API 能力

- **视觉模型**：可在当前档案配置 `vision_base_url` + `vision_model`，也可用 `vision_profile_id` 关联一个以主 `base_url + model + key` 提供视觉能力的完整档案。两种方式互斥，关联档案优先；未配置或洋红测试图识别失败时 Reference Analyzer 明确报错，不会把文本模型伪装成视觉模型。
- **DeepSeek 结构化输出（0.2.1）**：Responses 路径原生支持 `text.format` json_schema（`structured_output_responses=True`，flash）；Chat 路径官方未文档化 json_schema → 自动降级为「提示词约束 + 客户端解析校验」（`structured_output_chat=False`）。**不再**因 `provider==deepseek` 统一禁止原生结构化输出。
- **DeepSeek 附件能力（0.2.1）**：`deepseek-v4-flash` **不支持图片/文件输入**（官方：`input_image` 被替换为占位文本，`input_file` 未文档化）——能力表诚实标记 vision=False / files=False；图片附件明确报错，PDF/DOCX 走本地文本提取降级。
- **DeepSeek 按具体模型能力**：`deepseek-v4-flash`（responses/web_search 原生）；`deepseek-v4-pro`（responses 当前不可用）等以 `DEEPSEEK_MODEL_CAPS` 表与能力探测缓存为准；未知模型保守走 chat_completions。
- **联网搜索**：原生 web_search 仅 DeepSeek Responses 路径；其他端点按降级链：外部搜索后端（档案 `search_url`）→ 离线 + 明确警告。**外部搜索后端是自定义 HTTP 契约**（POST {query} → {results:[{title,url,snippet}]}），不是内置搜索服务，需要用户自建或接入第三方网关。
- **函数工具**：内置 `now` / `search` 两个工具；`search` 依赖档案 `search_url`。工具循环上限 `MAX_TOOL_ROUNDS=4`（不暴露到节点 UI）。工具执行失败把错误文本回给模型，不抛异常、不伪造。Responses 续轮的 `call_id` 逐字沿用模型返回值。

## 2. 本地运行时

- 只控制**独立运行的本地服务**（Ollama / llama.cpp / LM Studio / 自定义兼容服务），不把模型加载进 ComfyUI 进程。
- Ollama 无官方 load/unload 端点：以「空请求预热 + `keep_alive:0` 卸载 + `/api/ps` 状态」模拟；LM Studio v0 只读（状态可读，load/unload 明确报错不伪装）；**LM Studio v1（0.2.1a）**模型标识以官方 `key` 字段为准（`id` 仅存在于 `loaded_instances` 实例条目；v0 才是 `data`+`id`），实现兼容 key/id 两代。
- `unload_policy` 仅对 `provider=local` 生效（after_request / after_success / never）；卸载失败只追加 warning，不影响生成结果。

## 3. 多图身份判断

- 身份判断流程（0.2.1）：先做一次 **VLM 整体判断**（最多 6 张代表图；只比较可观察身份特征——脸型比例/发际线/眼形/鼻口几何/明显印记/身体比例，服装/背景/姿势为弱辅助）→ 失败时回退「stable 特征名与值」文本一致度启发式。两者都是判断依据，不是视觉重识别。
- **VLM 结论为 merge 权威（0.2.1a）**：VLM same_subject=True → 合并全部候选（即使 stable 字符串不一致，冲突标记 uncertain）；False → 禁止全量合并（主主体 + `__subject_identity__` 冲突，防跨主体串绑）；字符串一致度启发式只在 VLM 不可用时作 fallback，不再覆盖 VLM 结论。**0.2.1b**：启发式无法把候选分组（全聚成一组）时也绝不全量合并——只取置信度最高的一张作主人物，其余保留身份冲突。
- **图片-only 分析不要求文本档案 Key（0.2.1b）**：Reference Analyzer 按需取密钥——有 text_anchor 才要求文本档案 Key，有 images 才要求视觉档案 Key（支持 vision_profile_id 解耦）；Text Provider ≠ Vision Provider。
- 多主体场景：只合并最高一致度分组，其余图不并入该人物（`__subject_identity__` 冲突记录），不会把不同主体的特征混合进同一个人物。

## 4. 附件 / 文件

- 附件文件路径只允许相对 ComfyUI input 目录；绝对路径或 `..` 穿越被拒绝。大小上限：文本 512KB / 图片 20MB / 文件 20MB。
- 附件内容**不进日志**；data URI 只在请求体与节点间传递。
- **文档解析（0.2.1）**：Provider 无 file 能力时，**PDF / DOCX 支持本地提取文本**（pypdf / python-docx，可选依赖）→ 文本附件 + warning「已本地提取文本发送」。**不 OCR**：扫描 PDF 无文本层 → 明确报错，不假装识别。**PPTX / XLSX 不做本地提取**（需要 Provider 原生 file 能力，否则报错）。文本类附件（TXT/MD/JSON/CSV/HTML 等）始终直接作为文本发送。
- **提取截断（0.2.1a）**：本地提取文本按 UTF-8 **字节**截断并回退到有效字符边界（此前按字符数截断，中文长文档会超过 512 KB）。
- **附件 warning 必达节点**（0.2.1）：路径越界 / 文件不存在 / 超限 / 被跳过 / 本地提取降级，全部出现在 LLM Generate 的 `warnings` 输出，不静默丢弃。

## 5. Markdown 补充资料

- 运行时不再加载 YAML Prompt Skill。目标硬规则由 `prompting/model_cores.py` 单独持有。
- 设置工作台管理本地 `.md` 资料；每份资料限制 256 KiB，校验 UTF-8、路径、SHA-256 和适用范围。资料默认不自动进入请求，节点必须显式填写 ID；目标 Studio 的 `auto` 只选择当前目标的已启用资料。
- 停用、改内容、改目标或删除资料会改变/移除 supplement fingerprint；已有绑定会话下一轮先报上下文变化。资料只能作为低优先级参考，不能覆盖协议、validator、锁定事实或最新用户请求。

## 6. 结构化输出 / 解析

- LLM 输出解析是**容错但不保证 100%**：`extract_json_object` 支持裸 JSON / ```json 围栏 / 花括号块；失败即报可读错误，不静默返回空结果伪装成功。
- Prompt Studio 只维护成品提示词；损坏 JSON/标签/Schema 说明或确定性硬规则失败最多做一次内容保真的修复。仍失败时不做创意改写，直接保留上一 revision 并报错。

## 7. 前端 / 设置

- 设置面板为 ComfyUI 内嵌 vanilla JS 模态；密钥只经服务端 SecretStore 存储，前端只显示脱敏值，**工作流 JSON 与日志永不出现完整密钥**。
- **入口（0.2.1c）**：不注册 Sidebar Tabs，也不注入 `.comfy-menu`；入口放在 ComfyUI 原生 Settings 的 `AI Prompt Studio > General > Settings Workbench`。由于官方 Settings API 没有 button/action 类型，工作台入口用一次性 combo：选择「Open Settings Workbench」后打开大型 overlay，并自动恢复 idle。
- **原生 ComfyUI 设置**（0.2.1c）：`AI Prompt Studio.General.language`（zh/en）与 `AI Prompt Studio.General.openWorkbench`（一次性动作 combo）。**API Key 不作为前端设置项**——密钥仍只在服务端 SecretStore。
- 本扩展不拦截 ComfyUI 核心行为；不改动核心文件。
- ANIMA_BOOSTER 未安装 → 软检测（仅提示，无硬依赖）。

## 8. 未实现（明确不做）

- 视频生成/编辑本身（H3 只产出提示词文本）。
- 图像/视频渲染能力（本扩展是提示词工作流，不生成像素）。
- 内置搜索引擎（外部搜索后端需要用户提供）。
- DeepSeek 思考/推理关闭（reasoning=off 不做——DeepSeek 无官方禁用 thinking 的稳定接口）。
- 对第三方 GPL/受限项目（Prompt Assistant / TE_MAN / DaSiWa）代码的直接复制；只参考结构与产品语义，实现全部原创。
- 附件本地解析 PPTX / XLSX（见 §4）；H3 Ref2VA 之外的「自动翻译」不做（不假装翻译）。
- 静态 Reference Analyzer 不做镜头运动推断（camera motion 由 H3 Prompt Studio 生成阶段决定）。

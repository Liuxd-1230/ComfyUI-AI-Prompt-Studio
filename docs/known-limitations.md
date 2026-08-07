# 已知限制 known-limitations.md

本文记录本扩展**已明确不接受或未实现**的能力边界，以及对应的行为约定。
凡与官方文档冲突之处以官方为准；凡此处标注「未实现」的功能不会被伪装为可用。

## 1. 模型 / API 能力

- **视觉模型**：必须由用户在档案中配置 `vision_base_url` + `vision_model`（OpenAI 兼容多模态端点）或 `vision_profile_id`（视觉/文本 Profile 解耦）。未配置时 Reference Analyzer 明确报错，不会把文本模型伪装成视觉模型。
- **DeepSeek 结构化输出**：DeepSeek 官方未文档化 Chat `json_schema` / Responses `json_schema` 支持；网关对 DeepSeek 自动降级为「提示词约束 + 客户端解析校验」，不发送未文档化参数。
- **DeepSeek 按具体模型能力**：`deepseek-v4-flash`（responses/web_search 原生）；`deepseek-v4-pro`（responses 当前不可用）等以 `DEEPSEEK_MODEL_CAPS` 表与能力探测缓存为准；未知模型保守走 chat_completions。
- **联网搜索**：原生 web_search 仅 DeepSeek Responses 路径；其他端点按降级链：外部搜索后端（档案 `search_url`）→ 离线 + 明确警告。**外部搜索后端是自定义 HTTP 契约**（POST {query} → {results:[{title,url,snippet}]}），不是内置搜索服务，需要用户自建或接入第三方网关。
- **函数工具**：内置 `now` / `search` 两个工具；`search` 依赖档案 `search_url`。工具循环上限 `MAX_TOOL_ROUNDS=4`（不暴露到节点 UI）。工具执行失败把错误文本回给模型，不抛异常、不伪造。

## 2. 本地运行时

- 只控制**独立运行的本地服务**（Ollama / llama.cpp / LM Studio / 自定义兼容服务），不把模型加载进 ComfyUI 进程。
- Ollama 无官方 load/unload 端点：以「空请求预热 + `keep_alive:0` 卸载 + `/api/ps` 状态」模拟；LM Studio v0 只读（状态可读，load/unload 明确报错不伪装）。
- `unload_policy` 仅对 `provider=local` 生效（after_request / after_success / never）；卸载失败只追加 warning，不影响生成结果。

## 3. 多图身份判断

- 身份一致度基于 LLM 输出的 **stable 特征名与值**的文本一致比例；同名不同值即视为分歧。这是启发式判断，不是视觉重识别。
- 多主体场景：只合并最高一致度分组，其余图不并入该人物（`__subject_identity__` 冲突记录），不会把不同主体的特征混合进同一个人物。

## 4. 附件 / 文件

- 附件文件路径只允许相对 ComfyUI input 目录；绝对路径或 `..` 穿越被拒绝。大小上限：文本 512KB / 图片 20MB / 文件 20MB。
- 附件内容**不进日志**；data URI 只在请求体与节点间传递。

## 5. Prompt Skill

- 内置技能（仓库 `skills/`）只读；要修改需「复制为自定义」后编辑。自定义技能存于用户配置目录 `skills/`。
- 技能字段白名单校验（id/version/target_family/target_variant/renderer/system_prompt/validators/description）；renderer / target_family 限枚举；未知字段被忽略并告警。
- `enabled=false` 的自定义技能仍可被 `get_skill` 读到（Composer 使用方自行判断是否尊重 enabled 标记）。

## 6. 结构化输出 / 解析

- LLM 输出解析是**容错但不保证 100%**：`extract_json_object` 支持裸 JSON / ```json 围栏 / 花括号块；失败即报可读错误，不静默返回空结果伪装成功。
- H3 渲染为确定性 Python（三字段/六段、时间戳、媒体编号、R2V 英文）；校验发现问题 → 一次 LLM 修复（auto_repair 默认开）；仍失败记 validation error。**不做假装翻译**（R2V 非英语正文不翻译，只报错）。

## 7. 前端 / 设置

- 设置面板为 ComfyUI 内嵌 vanilla JS 模态；密钥只经服务端 SecretStore 存储，前端只显示脱敏值，**工作流 JSON 与日志永不出现完整密钥**。
- 本扩展不拦截 ComfyUI 核心行为；不改动核心文件。
- ANIMA_BOOSTER 未安装 → 软检测（仅提示，无硬依赖）。

## 8. 未实现（明确不做）

- 视频生成/编辑本身（H3 只产出提示词文本）。
- 图像/视频渲染能力（本扩展是提示词工作流，不生成像素）。
- 内置搜索引擎（外部搜索后端需要用户提供）。
- DeepSeek 思考/推理关闭（reasoning=off 不做——DeepSeek 无官方禁用 thinking 的稳定接口）。
- 对第三方 GPL/受限项目（Prompt Assistant / TE_MAN / DaSiWa）代码的直接复制；只参考结构与产品语义，实现全部原创。

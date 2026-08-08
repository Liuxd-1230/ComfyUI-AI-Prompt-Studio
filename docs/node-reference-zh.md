# 节点端口参考

本页对应当前 11 个 `APS_` 节点。`必填`是节点控件或必须连接的端口，`可选`未连接时使用节点默认值。自定义类型只能连接同名类型；普通 `STRING` 可接其他 ComfyUI 文本节点。

## APS_ModelProfile · AI 模型档案

输入：`profile` 选择“名称 [ID]”；`model_override` 从实测模型目录选择覆盖模型；`custom_model_override` 手填不在目录中的模型并优先于下拉；`protocol` 控制 auto/Responses/Chat；`reasoning` 是推理强度；`web_search` 是联网策略；`unload_policy` 是本地 LLM 请求后的卸载时机。输出 `AI_PROFILE`，只含档案引用和运行覆盖，不含 API Key。

推荐连接：`AI_PROFILE → LLM Generate / Reference Analyzer / Storyboard Builder / Prompt Composer / H3 Director`。

## APS_LLMGenerate · LLM 生成/对话

输入：`AI_PROFILE`（必连）；`system_prompt` 定义角色和硬约束；`user_prompt` 是本轮任务；`context` 是补充资料，不应放指令；`session` 接上一轮 `CHAT_SESSION`；`history_mode` 控制追加、替换或禁用历史；`output_mode` 选择文本/JSON/JSON Schema；`json_schema` 仅在 schema 模式填写；`attachments` 接附件列表；`attachment_files` 从 ComfyUI input 目录读取相对路径。

输出：`text` 最终回答；`reasoning` 是服务公开返回的推理摘要/内容；`CHAT_SESSION` 供下一轮；`LLM_RESULT` 是完整结构；`citations`、`usage`、`warnings` 是 JSON/文本诊断。

## APS_ReferenceAnalyzer · 参考分析

输入：`AI_PROFILE`；`analysis_mode` 选择分析目标；`text_anchor` 提供已知事实；`images` 接 IMAGE 批次；`character_bible` 提供已有身份；`custom_prompt` 仅 custom 模式使用。

输出：`REFERENCE_ANALYSIS` 是本次结构化分析；`CHARACTER_CANDIDATE` 可接 Character Bible；`REFERENCE_MANIFEST` 保存资产与主体映射；`caption/confidence/raw` 用于预览诊断；`IMAGES` 原样透传图片。

## APS_ReferencePrompt · 图片引用提示词

输入：`prompt` 中键入 `@` 选择已连接图片；`target` 决定引用语法；`image_1..3` 按实际连接顺序编号。输出 `prompt`（Qwen 为 `Figure N`，H3 为 `<Picture N>`）；`REFERENCE_MANIFEST` 接 Composer/H3；`references` 是引用对照文本；`count` 是有效图片数。

## APS_CharacterBible · 人物档案

输入：`merge_strategy` 决定冲突优先级；`character_candidate` 接分析结果；`existing_bible` 更新单个人物；`existing_book` 更新多人集合；`text_anchor` 增补人工事实；`lock_fields` 用逗号分隔不可改字段；`character_name` 是显示名。

输出：`CHARACTER_BIBLE` 单人物结构；`character_prompt` 可读身份片段；`json` 完整 JSON；`conflict_report`、`uncertainty` 供人工复核；`CHARACTER_BOOK` 是多人集合；`warnings` 说明合并与 ID 分配。

## APS_StoryboardBuilder · 分镜构建

输入：`AI_PROFILE`；`story_text` 是故事而非成品提示词；`split_mode` 控制场景/镜头/节拍粒度；`target_duration` 是全片目标秒数；`max_scenes` 是硬上限；`style` 是全局视觉方向；可选人物档案、人物集合和参考清单提供连续性约束。

输出：`STORYBOARD` 接 Select/H3；`story_summary` 是摘要；`continuity` 列出人物、场景、时长与降级警告。

## APS_StoryboardSelect · 分镜选择/批处理

输入：`storyboard`；`select_mode` 选择 scene/shot/range/all；`scene_id`、`shot_id` 用结构中的稳定 ID；`range` 用 `1-3` 等序号范围。输出 `STORY_ITEM` 单项；`STORY_ITEM_LIST` 容器；`scene_text` 可读文本；`character_ids`；`batch_count`；`STORY_ITEMS` 是 ComfyUI 真列表输出，可驱动列表感知节点。

## APS_PromptComposer · 模型提示词编排

输入：`AI_PROFILE`；`text` 是构想或待处理提示词；`target` 选择目标模型；`operation` 决定生成/扩写/改写/翻译/审计/修复/转换；`prompt_mode` 控制 ANIMA/Generic 的标签或自然语言形态；`negative` 覆盖负面词；`safety_tag` 仅按用户明确选择添加。可选端口接分镜项、人物档案/集合、参考清单、自定义 Skill 和 LoRA 触发词。

输出：`positive/negative` 直接接下游文本编码；`PROMPT_PLAN` 是结构化中间计划；`GENERATION_PROFILE` 给出步数/CFG 等建议；`validation` 有 error 时不要继续生成。

## APS_MiniMaxH3Director · H3 导演

输入：`AI_PROFILE`；`text` 是剧情任务或待审计成品；`mode` 是 T2VA/I2VA/FL2VA/L2VA/Ref2VA；`operation` 控制生成、改写、分镜转换、审计或修复；`duration` 必须 4–15 秒；`auto_repair` 允许一次修复。可选接 Storyboard、人物资料、Manifest、IMAGE 批次及 3 路 VIDEO/3 路 AUDIO。

输出：`prompt` 是可接 MiniMax H3 生成节点的最终 STRING；`H3_PROMPT_PLAN` 是可编辑结构；`REFERENCE_MANIFEST` 是同步后的媒体清单；`validation` 是规则报告；`warnings` 是回退/修复说明。

## APS_RuntimeControl · 本地运行时

输入：`backend` 选择 Ollama/llama.cpp/LM Studio/custom；`action` 选择状态、列模型、加载、卸载、重载或全部卸载；`url` 留空用后端默认地址；`model` 在模型动作时填写；可选 `AI_PROFILE` 用于把运行状态继续向下传。

输出：`AI_PROFILE` 透传并更新 runtime；`runtime_status` 是 JSON 状态；`loaded_models` 是当前已加载模型；`operation_result` 是动作结果。该节点不把模型加载进 ComfyUI Python 进程。

## APS_UnloadModel · LLM 后卸载 LM Studio

输入：`model` 填 LM Studio 模型 key，留空表示卸载全部已加载实例；`prompt` 接 LLM/Composer 文本；`url` 留空使用 `http://127.0.0.1:1234`。输出 `prompt` 仅在卸载成功后透传；`result` 是 JSON；`status` 是中文结果。推荐串法：`LLM text → prompt → 本节点 prompt → 图像/视频 prompt`。

## 最小连接示例

```text
ModelProfile.AI_PROFILE ─┬→ LLMGenerate.AI_PROFILE
                         ├→ StoryboardBuilder.AI_PROFILE
                         └→ PromptComposer.AI_PROFILE

StoryboardBuilder.STORYBOARD → StoryboardSelect.storyboard
StoryboardSelect.STORY_ITEM   → PromptComposer.story_item
PromptComposer.positive       → UnloadModel.prompt → 下游模型 prompt
```

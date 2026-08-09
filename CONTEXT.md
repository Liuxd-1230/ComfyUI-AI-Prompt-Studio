# ComfyUI AI Prompt Studio

AI Prompt Studio 是一个 ComfyUI 自定义节点扩展：用 LLM 把自由文本、人物锚点、参考图与剧情，变成 ANIMA / MiniMax H3 / 通用图像模型可直接使用的提示词，并负责 LLM 服务（云端/本地）的配置、探测与显存交接。

## Language

**Profile（档案）**：
设置工作台中命名的一组 LLM 服务配置：Provider、URL、模型名、协议、推理强度、联网策略、卸载策略与能力缓存。工作流 JSON 只保存 `profile_id`。
_Avoid_: 设置项、配置块

**Provider（提供商）**：
LLM 服务的供应商（如 DeepSeek、任意 OpenAI 兼容服务、本地运行时）。Profile 必属于一个 Provider。
_Avoid_: 厂商、上游

**Gateway（网关）**：
统一封装 LLM 调用入口：把 Profile 解析为请求、选择协议适配器、执行降级链、把原始响应归一化为 LLMResult。业务节点不得直接拼 HTTP。
_Avoid_: 客户端封装、API 层

**Adapter（协议适配器）**：
实现具体协议（Responses 或 Chat Completions）的请求构造与 SSE 响应解析。Gateway 之下，不感知业务语义。
_Avoid_: 转换器

**LLMResult（LLM 结果）**：
Gateway 的统一输出结构：text、reasoning、citations、tool_calls、usage、response_id、warnings、error。错误绝不伪装成普通模型回答。

**Capability（能力）**：
Profile 对应的服务支持什么（responses/chat_completions/function_tools/native_web_search/structured_output/vision/model_listing）。探测结果缓存，可手动重跑。

**降级链（fallback chain）**：
联网搜索在能力不支持时逐级回退（原生→函数工具→外部后端→离线+警告）。只有「接口或参数不支持」才降级；认证、余额、限流、5xx 错误一律不降级。

**Character Bible（人物档案）**：
人物稳定身份的总和：stable traits、variable traits、locked fields、source tracking、uncertainty、置信度，以及人物 ID 与 H3 Speaker ID。由文字锚点、视觉结果与人工设定合并而来。
_Avoid_: 人设卡

**Character Candidate（人物候选）**：
Reference Analyzer 对单张图（或单次分析）产出的人物特征推断，带置信度与来源证据。多个 Candidate 通过合并策略收敛成 Bible。

**Reference Analysis（参考分析）**：
一次视觉/文字分析的结构化输出（模式如 character_identity、scene、style……），可产出 Candidate 与 Manifest 更新。

**Reference Manifest（参考清单）**：
原始资产的注册表：图片/视频/音频路径或引用、时间裁剪信息、Subject 映射、H3 标签、人物来源与置信度。保留原始资产本身。

**Storyboard（分镜）**：
模型无关的场景/镜头/节拍（scene/shot/beat）结构化拆分，保持人物与场景连续性；不直接写 ANIMA 或 H3 最终格式。
_Avoid_: 剧本拆分

**Prompt Plan（提示词计划）**：
Composer 面向目标图像模型（ANIMA/Generic/SDXL/FLUX/自定义 Skill）生成的中间计划：正负提示词、目标模型、模式、校验结果。
_Avoid_: 成稿

**Prompt Session（提示词会话）**：
Prompt Studio 的持久领域状态：Current Plan、Current Prompt、revision、最近版本、锁定约束、validation 与简短会话。由后端产生并写回 workflow widget；不依赖 Python 节点实例，也不靠重放聊天记录推断当前状态。

**Generation Profile（生成档案）**：
目标图像模型的采样参数建议（步数、CFG、调度器等），随 Prompt Plan 输出，供后续采样节点使用。

**H3 Prompt Plan（H3 提示词计划）**：
H3 Director 的中间结构化计划：模式（T2VA/I2VA/FL2VA/L2VA/R2V）、镜头、说话人、标签映射、声音与音乐字段；经 Python 渲染器变成最终 STRING 提示词。

**H3 模式（H3 mode）**：
T2VA（纯文本）、I2VA（首帧锚定）、FL2VA（首尾帧路径）、L2VA（尾帧收敛）、R2V（全参考重写）。

**Speaker ID（说话人 ID）**：
H3 提示词中的稳定说话人标记（S1/S2，复合 S1,S2），跨镜头保持一致，与 Character Bible 的人物 ID 映射。

**Skill（提示词技能）**：
模型专用规则包（YAML）：id/version/target/renderer/system_prompt/validators/source/hash。内置官方 Skill 只读，用户可复制后编辑。
_Avoid_: 模板、预设

**Renderer（渲染器）**：
把结构化计划（Prompt Plan / H3 Prompt Plan）确定性地渲染为目标模型文本格式（ANIMA 标签串、H3 三字段/六段）。

**Validator（验证器）**：
对渲染结果执行规则检查（H3 时间戳、六段顺序、标签完整性；ANIMA 冲突标签、重复标签等），产出可读报告。

**Runtime（本地运行时）**：
独立运行的本地 LLM 服务（Ollama/llama.cpp/LM Studio），支持查询、加载、卸载、重载与全部卸载，用于释放显存给图像/视频模型。

**Unload Policy（卸载策略）**：
Profile 记录的本地模型卸载时机：never / after_request / after_success。

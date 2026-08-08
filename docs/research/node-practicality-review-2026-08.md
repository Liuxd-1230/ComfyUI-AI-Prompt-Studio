# 节点与提示词实用性调研（2026-08）

## 范围与结论

本次对照仓库 10 个节点、内置 Prompt Skill、用户的 `t2v.json`，并核对 ComfyUI、LM Studio、llama.cpp、Black Forest Labs、Stability AI 等一手资料。整体判断：**H3 的结构化计划/确定性渲染/校验链和 ANIMA 专用渲染器方向正确；通用 Composer、批处理、运行时状态和节点可发现性仍有明显产品缺口。** 现有 452 项测试主要验证结构和协议，不能证明最终图片/视频提示词质量。

## P0：会直接让功能名不副实

1. **Profile 覆盖参数下游丢失。** `APS_ModelProfile` 将 `model_override`、`protocol`、`reasoning`、`web_search`、`unload_policy` 写入 `AI_PROFILE`，但 LLM、Reference、Storyboard、Composer、H3 节点随后仅按 `profile_id` 重新读取设置档案，覆盖值未合并。应增加统一的 `resolve_effective_profile(payload)` 并做端到端测试。
2. **Storyboard “Batch” 不是真正的 ComfyUI 列表执行。** `STORY_ITEM_LIST` 只是一个 JSON 自定义类型，没有下游消费者，也没有 `OUTPUT_IS_LIST`；因此不会逐镜头驱动 Composer。ComfyUI 官方要求用 `OUTPUT_IS_LIST` 暴露逐项执行列表：[Data lists](https://docs.comfy.org/custom-nodes/backend/lists)。
3. **Composer 的 `reference_manifest` 是未使用输入。** 接上线也不会影响 ANIMA/SDXL/FLUX 输出；`GENERATION_PROFILE` 同样没有仓库内消费者。应删除虚假接口或真正接入 renderer/采样参数应用节点。
4. **SDXL/FLUX 不是专用实现。** `expand/rewrite/repair` 仍复用 ANIMA Skill，`repair` 甚至跑 ANIMA validator。`flux_kontext` 没有图片输入，也没有明确“哪张参考图用于主体/风格/背景”的语义。BFL 官方说明 FLUX.2 不使用 negative prompt、强调主语优先和每张参考图的角色：[FLUX.2 Prompting Guide](https://docs.bfl.ai/guides/prompting_guide_flux2)。应拆成独立 family renderer、schema、validator；Kontext/FLUX.2 编辑必须消费图像。

## P1：真实工作流中容易失败或难用

- **运行时副作用契约不完整。** `APS_RuntimeControl` 没有 `OUTPUT_NODE`/`IS_CHANGED`，独立放置可能不执行或被缓存。ComfyUI 明确从输出节点反向执行，并缓存输入未变的节点：[Execution control](https://docs.comfy.org/custom-nodes/backend/server_overview)。专用卸载节点虽有 `IS_CHANGED=NaN`，仍只适合串在 prompt 链内。
- **LM Studio 状态语义混淆。** `/api/v1/models` 返回可用模型及 `loaded_instances`；当前实现把全部 key 当作“已加载模型”，`unload_all` 会尝试卸载未加载项；同一 key 多实例只卸第一个。应分别返回 available/loaded instances，并允许按 instance 或全部实例卸载。LM Studio v1 官方端点见 [REST API](https://lmstudio.ai/docs/developer/rest)。
- **LM Studio Token 不受支持。** Runtime HTTP 层不发送 Authorization；开启 “Require Authentication” 后状态与卸载都会失败。官方要求 Bearer token：[Server Settings](https://lmstudio.ai/docs/developer/core/server/settings)。Token 应复用 SecretStore，不能进入工作流 JSON。
- **自动卸载配置难以实际使用。** Profile 有隐藏的 `runtime` 字典但设置工作台不能编辑；默认 backend 又是 Ollama。更实用的方案是卸载节点可接 `AI_PROFILE` 或 `LLM_RESULT`，自动取得实际 backend/url/model/token，同时保留 prompt 透传。
- **Storyboard 约束只写进提示词、未强制。** `max_scenes`、总时长和镜头 ID 唯一性缺少确定性校验；模型漏写 duration 时按“每个场景”分摊，可能令全片总时长超过目标。`continuity` 目前只报告人物跨场景出现，并未检查服装、位置、道具状态。
- **Reference Analyzer 成本不可控。** 多图逐张串行分析，再追加一次身份判断；只限制身份判断取前 6 张，却不限制逐图分析总数。应增加 `max_images`、并发上限、缩略图策略和成本预估。
- **Skill 管理 UI 未完成。** 后端有 create/update，但前端只有复制、启停、删除，没有编辑 `system_prompt` 的表单；界面却声称复制后可编辑。
- **LLM 的 context 被放进 system 消息。** 虽有“把上下文当数据”的文字守则，但把外部资料提升到 system 层仍扩大提示注入风险；应作为独立 user/context content part，并使用明确边界。

## P2：质量与维护升级

- 为每个节点增加中文富文档、连接示例和搜索别名。ComfyUI 已原生支持 `WEB_DIRECTORY/docs/<Node>/zh.md`：[Node documentation](https://docs.comfy.org/custom-nodes/help_page)。目前 `web/docs` 不存在。
- 逐步迁移 V3 node schema，获得正式的 `display_name`、advanced 输入、async execute、progress reporting 等能力；官方称未来节点特性将只加入 V3：[V3 Migration](https://docs.comfy.org/custom-nodes/v3_migration)。
- Composer 的 ANIMA plan 应使用原生 JSON Schema（当前仅在 system prompt 中要求 JSON），减少小型本地模型解析失败。
- 所谓“流式”目前只是在服务端累计 SSE，ComfyUI 用户看不到增量输出；应增加 progress/preview，或把 README 改成“流式协议兼容”。
- 加入真实质量评测：固定 20–30 个单人、多人物、构图、文字、参考编辑、短视频用例；保存 seed/模型版本；对比原始提示词与 Composer 输出，做盲评和失败分类。SDXL 官方模型卡也明确列出文字、复杂构图、人物等限制：[SDXL model card](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0)。

## 对现有节点的实用性评分

| 节点 | 当前实用性 | 说明 |
|---|---:|---|
| Model Profile | 4/10 | 配置集中化好，但覆盖参数丢失是核心缺陷 |
| LLM Generate / Chat | 7/10 | 协议、附件、会话较全；无可见流式，context 分层需修 |
| Reference Analyzer | 7/10 | 结构合理；多图成本与上限不足 |
| Character Bible | 7/10 | 多人物/Speaker ID 有价值；编辑体验仍偏 JSON 管线 |
| Storyboard Builder | 6/10 | 可用，但约束和连续性校验偏浅 |
| Storyboard Select / Batch | 3/10 | 选择可用，“Batch”尚未落地 |
| Prompt Composer—ANIMA | 8/10 | 当前最成熟的图片提示词路径 |
| Prompt Composer—SDXL/FLUX | 3/10 | 名称覆盖多模型，实际仍是通用/ANIMA 逻辑 |
| MiniMax H3 Director | 8/10 | 架构最强；仍需要真实生成质量回归集 |
| Runtime Control | 4/10 | API 覆盖广，但执行、状态、认证语义不完整 |
| LM Studio Prompt Pass-through Unload | 7/10 | 对当前显存接力场景实用；应自动取模型/token并处理多实例 |

## 建议实施顺序

先修 Profile effective config、真正的 list batch、LM Studio loaded-instance/token；随后拆分 ANIMA/SDXL/FLUX Prompt Skill 并让 reference manifest 真正生效；最后补中文节点文档、V3/进度反馈和真实生成评测。用户现有 `t2v.json` 中保存的仍是旧版、无连接的卸载节点，需在当前工作流把它插入 `TE_text_display → MiniMaxH3ImageToVideo.prompt` 之间后重新保存。

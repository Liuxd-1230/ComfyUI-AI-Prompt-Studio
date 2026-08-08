# 模型提示词编排器

ANIMA 的最终视觉描述和标签应使用英文。中文可作为 natural/hybrid 的生成、扩写、改写或修复输入，内置 Skill 会要求 LLM 保真转换成英文；角色名、专有名词与画面内文字可保留原文。`tags` 离线路径不做翻译，请直接输入英文标签。

`AI_PROFILE` 提供模型；`text` 写构想或待处理成品；`target` 选目标，`operation` 选操作，`prompt_mode` 选表现形式，`safety_tag` 仅按用户选择添加。可接 `story_item`、`character_bible`、`character_book`、`reference_manifest`、`skill` 和 `lora_triggers`。旧 `content_tier` 只用于工作流迁移。输出 `positive/negative`、结构化 `PROMPT_PLAN`、采样建议 `GENERATION_PROFILE` 与 `validation`。

目标：ANIMA Base/Aesthetic/Turbo；Z-Image Turbo；Qwen-Image-Edit-2511；Generic；Custom Skill。ANIMA 的 `tags` 输出标签串，`natural_language` 输出镜头散文，`hybrid` 输出少量控制标签+自然描述。Z-Image 期待详细自然语言（9 步、CFG 0、空负面）；Qwen 期待 `保持 Figure 1…把背景替换为 Figure 2…` 这种直接编辑命令。

操作：`generate` 从构想生成；`expand` 补细节；`rewrite` 保留意图重写；`translate` 只翻译；`audit` 离线检查；`repair` 按报告修；`convert` 确定性转换。第三方端点返回普通文本时会保留原文并 warning，不再因缺 JSON 崩溃。

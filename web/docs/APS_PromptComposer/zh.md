# 模型提示词编排器

ANIMA 的最终视觉描述和标签应使用英文。中文可作为 natural/hybrid 的生成、扩写、改写或修复输入，内置 Skill 会要求 LLM 保真转换成英文；角色名、专有名词与画面内文字可保留原文。`tags` 离线路径不做翻译，请直接输入英文标签。

`AI_PROFILE` 提供模型；`text` 是第一次的生成要求，之后改为填写你看图后的最新修改意见；`target` 选目标，`prompt_mode` 选表现形式，`safety_tag` 仅按用户选择添加。有 `prompt_session` 中的有效 Plan 时自动 REFINE，没有时自动 CREATE；重新开始只能显式使用“新会话”。`continue_previous` 仅保留旧 workflow 端口位置，工作台不再显示或依赖它。`session_action` 由“恢复上一版为新版本/新会话”按钮维护；`prompt_session` 是随 workflow 保存的结构化状态。`message_nonce` 由工作台自动维护，用来防止重复 Queue 再次处理同一消息，请勿手工填写。可接 `story_item`、`character_bible`、`character_book`、`reference_manifest`、`skill` 和 `lora_triggers`。旧 `content_tier` 只用于迁移。

REFINE 首次未返回合法 ChangeSet 时会带着去重后的协议问题重试一次；第二次仍失败会显示截断的模型原始输出，当前 Prompt 与 revision 不变。恢复按钮只有在至少存在两个成功 revision 时才可执行。

输出 `positive/negative`、结构化 `PROMPT_PLAN`、采样建议 `GENERATION_PROFILE` 与 `validation`。节点内 Current Prompt 与 `positive` 同步；成功 revision 才写回会话。最近 10 个 revision 是不可变快照；恢复旧版会创建新 revision，不删除后续历史。校验或 patch 失败时保留上一版。

目标：ANIMA Base/Aesthetic/Turbo；Z-Image Turbo；Qwen-Image-Edit-2511；Generic；Custom Skill。ANIMA 的 `tags` 输出标签串，`natural_language` 输出镜头散文，`hybrid` 输出少量控制标签+自然描述。Z-Image 期待详细自然语言（9 步、CFG 0、空负面）；Qwen 期待 `保持 Figure 1…把背景替换为 Figure 2…` 这种直接编辑命令。

新 UI 隐藏 `operation`：程序按是否存在 current Plan 自动选择 CREATE/REFINE。ANIMA 保留专用语义 Plan；Z-Image、Qwen 与 Generic 把正文拆为可独立修改的语义片段，REFINE 只应用受校验的局部 patch。旧工作流中的 `generate/expand/rewrite/translate/audit/repair/convert` 仍由后端兼容。持久 CREATE 要求模型按协议返回结构化结果；解析失败不会写入 revision。

# MiniMax H3 提示词导演

`AI_PROFILE` 提供模型；`text` 第一次写导演任务，之后填写看过视频后的最新修改意见；`mode` 选模式，`duration` 只能 4–15 秒，`auto_repair` 最多修复一次。有 `prompt_session` 时基于当前 `H3PromptPlan` 做最小 patch；重新开始只能显式使用“新会话”。`continue_previous` 仅保留旧 workflow 端口位置，工作台不再显示或依赖它。`session_action` 由“恢复上一版为新版本/新会话”按钮维护。`prompt_session` 随 workflow 保存 Plan、Prompt、validation、聊天和最近 10 个不可变 revision；恢复旧版会创建新 revision，不删除后续历史。`message_nonce` 由工作台自动维护，用来防止重复 Queue 再次处理同一消息，请勿手工填写。新 UI 隐藏 `operation`，旧 `generate/rewrite/convert_storyboard/audit/repair` 值仍兼容。

可选接 `storyboard`、`character_bible`、`character_book`、`reference_manifest`、IMAGE 批次 `images`，以及 `video_1`、`video_2`、`video_3`、`audio_1`、`audio_2`、`audio_3`。Storyboard 在 CREATE 时自动作为结构化上下文，不要求选择转换操作。

模式：T2VA 不接参考；I2VA 接 1 张首帧；FL2VA 接首尾 2 张；L2VA 接 1 张尾帧；Ref2VA 支持 Picture/Video/Audio（图片≤9、视频≤3、音频≤3、合计≤12）；R2V 是旧别名。

Ref2VA 任务示例：`<Picture 1> 保留人物身份与服装；<Video 1> 只参考奔跑节奏；<Audio 1> 在 Shot 2 保留脚步声。重演为雨夜车站追逐，8 秒。`

输出 `prompt` 接 H3 生成节点；`H3_PROMPT_PLAN` 是当前结构计划；`REFERENCE_MANIFEST` 是同步资产；`validation` 每版必跑；`warnings` 说明修复和回退。Current Prompt 预览与实际 `prompt` 同步；失败轮不覆盖上一版。

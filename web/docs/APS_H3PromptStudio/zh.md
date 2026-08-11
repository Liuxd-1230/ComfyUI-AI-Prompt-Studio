# MiniMax H3 提示词工作台（宽松 / 严格）

第一次执行自动 CREATE，成功写入 `prompt_session` 后自动 REFINE。节点只生成、检查
H3 提示词，不连接视频生成模型也能完成调试。

## 输入

- `AI_PROFILE`：连接 AI 模型档案。
- `text`：第一次写完整导演任务；之后只写本轮修改意见。
- `mode`：`T2VA` 纯文本；`I2VA` 首帧；`FL2VA` 首尾帧；`L2VA` 尾帧；
  `Ref2VA` 使用图片、视频、音频等参考。旧 `R2V` 值会归一化为 Ref2VA。
- `duration`：目标时长 4–15 秒。
- `execution_mode`：默认 `lenient` 直接维护完整 H3 文本；`strict` 保存结构化
  H3 Plan，以 ChangeSet 修改并经过 Diff Guard 和确定性 renderer。
- `session_action`：`continue`、`previous` 或 `new`。新会话只在新 CREATE 成功后替换旧状态。
- `storyboard`、`character_bible`、`character_book`：可选剧情和人物权威来源。
- `reference_manifest`：可选已有资产清单。
- `images`：I2VA/L2VA 连接 1 张，FL2VA 连接 2 张；Ref2VA 可连接图片批次。
- `video_1` / `video_2` / `video_3`：Ref2VA 视频参考，单项及总时长受官方边界检查。
- `audio_1` / `audio_2` / `audio_3`：Ref2VA 音频参考，不能作为唯一参考。
- `prompt_session`、`message_nonce`：工作台自动维护，通常不要手改。

## 输出

- `prompt`：可直接连接 MiniMax H3 视频节点的最终 STRING。
- `prompt_session`：最近 10 个成功 revision 的序列化状态。
- `REFERENCE_MANIFEST`：已按 Picture/Video/Audio 独立编号的资产清单。
- `validation`：模式、时长、时间戳、引用、媒体、说话人、声音和 Ref2VA 英语检查。
- `change_summary`：本轮创建或修改摘要。

## 模型输出要求

宽松模式要求 `<PROMPT>完整官方 H3 文本</PROMPT>` 与 `<SUMMARY>摘要</SUMMARY>`。
无标签但完整的普通 H3 文本会带黄色警告接收；半截 JSON、标签或协议说明只保真修复
一次。严格模式 CREATE 必须返回 H3 Plan JSON，REFINE 必须返回 ChangeSet；协议错误
也只修一次。两种模式都不会自动切换，也不会在 validator 失败后暗中改剧情。

除对白、歌词和画面文字外，H3 视觉/声音描述使用英语。T2VA 不连接图片；I2VA、
FL2VA、L2VA 的图片数量必须精确匹配。Ref2VA 会检查图片≤9、视频≤3、音频≤3、
混合≤12，以及视频/音频各自总时长≤15 秒。

# 图像提示词工作台（宽松 / 严格）

用同一个节点创建提示词并继续用自然语言修改。第一次执行是 CREATE；成功保存
`prompt_session` 后，后续执行自动成为 REFINE，不需要选择 operation。
节点本身是输出节点，可以单独 Queue 检查提示词和 validation，不必连接生成模型。

## 输入

- `AI_PROFILE`：连接“AI 模型档案”，提供模型、协议和密钥引用。
- `text`：第一次写完整画面要求，之后只写本轮修改意见。
- `target`：选择 ANIMA Base/Aesthetic/Turbo、Z-Image Turbo、Qwen Image
  Edit 2511 或 Generic Image。
- `execution_mode`：`lenient` 默认，直接维护完整提示词，最适合本地小模型；
  `strict` 维护结构化 Plan 和 ChangeSet，修改更可控，但更依赖模型正确输出 JSON。
- `session_action`：`continue` 继续，`previous` 把上一版恢复成新 revision，
  `new` 在本次 CREATE 成功后替换旧会话。
- `story_item`：可选分镜条目，与 `text` 合并为本轮要求。
- `character_bible` / `character_book`：可选人物身份与锁定特征。
- `reference_manifest`：可选参考资产清单；Qwen 的 `Figure N` 必须真实存在。
- `prompt_session`、`message_nonce`：工作台自动保存的状态和本轮消息编号，通常不要手改。

成功执行后，工作台会把 Session 写回隐藏字段并把工作流标为未保存；请保存工作流。
如果 ComfyUI 在回写前退出，重新打开旧工作流时会显示“Recover vN?”恢复确认，只有
明确同意才采用后端较新版本。复制节点会从当前成品建立独立会话，之后互不覆盖。

## 输出

- `positive`：可直接连接图像生成节点的最终正向提示词。
- `negative`：ANIMA 的默认或结构化负向提示词；Z/Qwen 通常为空。
- `prompt_session`：序列化会话，前端自动写回工作流。
- `validation`：本轮确定性检查和警告；未通过时不会提交新版。
- `change_summary`：模型或系统给出的简短修改摘要。

## 两种模式的预期输出

宽松模式要求模型返回 `<PROMPT>完整提示词</PROMPT>` 和
`<SUMMARY>摘要</SUMMARY>`。普通未加标签的完整提示词可带警告接收；损坏 JSON、
半截标签和协议说明会修复一次，仍失败则保留上一版。严格模式要求 CREATE 返回
结构化 Plan、REFINE 返回 ChangeSet，并经过 Diff Guard、renderer 和 validator。

ANIMA 的视觉正文必须为英语；姓名、专有名词、引用标签和引号内画面文字可以保留
原语言。节点不会自动从 strict 切换到 lenient，也不会暗中做创意语义重写。

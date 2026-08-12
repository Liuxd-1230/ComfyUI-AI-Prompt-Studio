# LLM 生成 / 对话

## 输入

`AI_PROFILE` 必连；`system_prompt` 写角色与硬约束；`user_prompt` 写本轮任务；`context` 只放资料。可选 `session`、`attachments` 和 input 目录相对路径 `attachment_files`。

展开节点底部的“高级设置 · Prompt Supplements”可多选 Markdown 资料。通用 LLM 只接受显式选择，不提供自动加载；资料作为低优先级参考数据，工作流仅在隐藏兼容字段 `prompt_supplements` 保存稳定 ID。

`history_mode`：`append` 追加历史，`replace` 新建仅含本轮的会话，`off` 单次请求。`output_mode`：`text` 普通文本，`json` 要求可解析 JSON，`json_schema` 同时读取 `json_schema` 控件。

## 输出

`text/reasoning` 是可读结果；`CHAT_SESSION` 接下一轮；`LLM_RESULT` 是完整结构；`citations/usage/warnings` 用于诊断。

示例：system=`你是分镜编辑，只输出可拍摄动作。`，user=`把这段剧情压缩成三个镜头。`

# AI 模型档案

从设置工作台选择模型服务，不在工作流中保存密钥。

## 输入

- `profile`：选择“档案名称 [profile_id]”；空值使用默认档案。
- `model_override`：从该档案实测得到的模型目录选择覆盖模型。
- `custom_model_override`：手填模型，优先于下拉。
- `protocol`：`auto` 按主动探测选择；也可强制 Responses/Chat。
- `reasoning`、`web_search`、`unload_policy`：本工作流的运行覆盖。

## 输出

`AI_PROFILE` 可同时连接 LLM、参考分析、分镜、Composer 和 H3；只含稳定档案 ID 与运行参数。

设置页“重新探测”会发送最小文本、JSON、工具、图片和文件请求，消耗少量 token，并把每项收敛为 true/false。

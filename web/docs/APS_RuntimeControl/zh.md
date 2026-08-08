# 本地运行时控制

`backend`：Ollama、llama.cpp、LM Studio 或 custom。`action`：`status` 健康状态；`list_models` 模型目录；`load/unload/reload` 操作 `model`；`unload_all` 只卸载当前已加载实例。`url` 留空使用后端默认地址；可选 `AI_PROFILE` 透传运行状态。

输出：更新后的 `AI_PROFILE`、JSON `runtime_status`、`loaded_models`、动作结果 `operation_result`。本节点控制外部服务，不会把模型加载进 ComfyUI Python 进程。

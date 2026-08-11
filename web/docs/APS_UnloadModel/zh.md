# LLM 后卸载 LM Studio

推荐连接：`LLM/Studio 文本 → prompt → 本节点 prompt → 图像/视频 prompt`。

`model` 填 LM Studio 模型 key；留空卸载全部当前已加载实例。`url` 本机通常留空。节点每次排队强制执行，先调用 LM Studio v1 unload，再透传 `prompt`；卸载失败会阻断下游，避免显存未释放仍继续加载生成模型。

输出：原样 `prompt`、JSON `result`（model/instance_ids/unloaded/error）和中文 `status`。

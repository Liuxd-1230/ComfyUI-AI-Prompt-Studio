# 分镜选择 / 批处理

不调用模型。`storyboard` 接 Storyboard Builder 输出；`select_mode=scene` 时，`scene_id` 可填顺序号 `1`、常见标签 `scene_01`/`场景1` 或真实 ID；`shot` 的 `shot_id` 同样可填扁平镜头序号 `1`、`shot_01`/`镜头1` 或真实 ID。留空选择该类型全部项目；`range` 在 `range` 填 `1-3`；`all` 选择全部镜头。找不到时错误会列出当前可用序号和 ID。

输出 `STORY_ITEM` 是单项，接 Prompt Composer；`STORY_ITEM_LIST` 是结构化容器；`scene_text` 供预览；`character_ids` 是人物 ID；`batch_count` 是数量；`STORY_ITEMS` 是 ComfyUI 真列表输出，供支持列表输入的节点逐项执行。

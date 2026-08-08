# 分镜选择 / 批处理

不调用模型。`storyboard` 接 Storyboard Builder 输出；`select_mode=scene` 使用 `scene_id`；`shot` 使用 `shot_id`；`range` 在 `range` 填 `1-3`；`all` 选择全部。

输出 `STORY_ITEM` 是单项，接 Prompt Composer；`STORY_ITEM_LIST` 是结构化容器；`scene_text` 供预览；`character_ids` 是人物 ID；`batch_count` 是数量；`STORY_ITEMS` 是 ComfyUI 真列表输出，供支持列表输入的节点逐项执行。

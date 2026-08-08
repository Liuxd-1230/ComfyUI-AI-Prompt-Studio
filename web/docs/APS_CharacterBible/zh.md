# 人物档案

输入 `character_candidate`、`existing_bible` 或 `existing_book`，并可用 `text_anchor` 增补人工事实；`character_name` 是显示名。`lock_fields` 用逗号分隔不可覆盖字段。

`merge_strategy`：`manual_priority` 已有人工值优先；`text_priority` 设定文字优先；`image_priority` 当前图片优先；`consensus` 只提升一致项；`fill_missing_only` 只补空值。

输出 `CHARACTER_BIBLE`、可读 `character_prompt`、完整 `json`、`conflict_report`、`uncertainty`、多人 `CHARACTER_BOOK` 和 `warnings`。多人 Speaker ID 在 Book 中唯一且稳定。

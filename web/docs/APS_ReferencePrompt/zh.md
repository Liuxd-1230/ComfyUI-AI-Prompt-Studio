# 图片引用提示词

把图片连接到 `image_1`、`image_2`、`image_3`，在 `prompt` 输入框键入 `@` 选择缩略图。编号按实际连接顺序生成，不会因为只接 image_2 就跳成 2。

`target=qwen_image_edit_2511` 输出 `Figure N`；`minimax_h3` 输出 `<Picture N>`；`generic` 保留可读引用。输出的 `prompt` 与 `REFERENCE_MANIFEST` 必须一起接 Composer/H3，避免文本引用与资产顺序不一致。

Qwen 示例：`保持 @图1 的人物不变，把背景替换为 @图2 的雨夜车站。`

输出：`prompt`、资产清单、引用对照 `references`、有效图片数 `count`。

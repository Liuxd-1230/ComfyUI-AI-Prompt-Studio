# 分镜构建

`AI_PROFILE` 提供生成模型。`story_text` 写故事和可拍摄动作，不写 ANIMA 标签或 H3 六段格式。`split_mode=scene` 按场景，`shot` 按镜头，`beat` 按动作/对白节拍，`auto` 自动选择。`target_duration` 是全片目标秒数，`max_scenes` 是硬上限，`style` 是全局视觉方向。

可接 `character_bible`、多人 `character_book` 和 `reference_manifest` 保持连续性。输出 `STORYBOARD` 接 Select/H3，`story_summary` 是摘要，`continuity` 显示人物、场景、时长与降级警告。

示例：`雨夜，铃冲进空车站寻找即将离开的朋友，在末班车关门前看见对方。`

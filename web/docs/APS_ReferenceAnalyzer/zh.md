# 参考分析

`AI_PROFILE` 提供文字与视觉档案；`images` 接 IMAGE 批次；`text_anchor` 写已知事实；`character_bible` 提供已有身份；`custom_prompt` 仅 custom 模式使用。

`analysis_mode` 模式：`character_identity` 只取稳定身份；`character_full` 全身设定；`clothing` 服装；`pose_expression` 姿势表情；`scene` 场景；`composition` 构图；`style` 媒介风格；`object` 物件；`anima_reference` 提取 ANIMA 可用词；`h3_reference` 建静态 H3 参考；`custom` 按自定义问题且禁止猜测。

输出 `REFERENCE_ANALYSIS` 是本次完整分析；`CHARACTER_CANDIDATE` 接 Character Bible；`REFERENCE_MANIFEST` 接 Storyboard/Composer/H3；`caption/confidence/raw` 用于人工复核；`IMAGES` 原样透传。

示例锚点：`角色名铃，成年女性，红色短发；只确认图片可见特征。`

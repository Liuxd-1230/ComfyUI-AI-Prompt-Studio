# 参考分析

视觉来源有两种互斥配置：设置 `vision_profile_id` 时，使用关联档案的主 API URL、主模型和密钥；留空时，使用当前档案的 `vision_base_url`、`vision_model` 和密钥。能力探测会向最终选中的模型发送一张 8×8 洋红测试图，只有模型正确识别颜色才确认视觉可用。

`AI_PROFILE` 提供文字与视觉档案；`images` 接 IMAGE 批次；`text_anchor` 写已知事实；`character_bible` 提供已有身份；`custom_prompt` 仅 custom 模式使用。

展开节点底部的“高级设置 · Prompt Supplements”可自动加载适用资料或显式多选。选择结果保存在隐藏兼容字段 `prompt_supplements`；资料只作参考，不会覆盖视觉观察守则和结构化输出契约。

`analysis_mode` 模式：`character_identity` 只取稳定身份；`character_full` 全身设定；`clothing` 服装；`pose_expression` 姿势表情；`scene` 场景；`composition` 构图；`style` 媒介风格；`object` 物件；`anima_reference` 提取 ANIMA 可用词；`h3_reference` 建静态 H3 参考；`custom` 按自定义问题且禁止猜测。

输出 `REFERENCE_ANALYSIS` 是本次完整分析；`CHARACTER_CANDIDATE` 接 Character Bible；`REFERENCE_MANIFEST` 接 Storyboard/Image Prompt Studio/H3 Prompt Studio；`caption` 是用户可直接查看或连接到文本节点的多行人物锚点摘要，按“稳定特征 / 可变特征 / 当前状态 / 不确定（请复核）/ 来源”分组；`confidence/raw` 用于人工复核；`IMAGES` 原样透传。图片-only 分析会留空未知姓名，不会把海报标题、Logo、文件名或 `Unknown` 当成人名。

示例锚点：`角色名铃，成年女性，红色短发；只确认图片可见特征。`

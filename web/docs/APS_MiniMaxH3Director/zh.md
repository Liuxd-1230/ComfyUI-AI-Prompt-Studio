# MiniMax H3 提示词导演

`AI_PROFILE` 提供模型；`text` 写导演任务或待审计成品；`mode` 选模式，`operation` 选操作，`duration` 只能 4–15 秒，`auto_repair` 允许一次修复。可选接 `storyboard`、`character_bible`、`character_book`、`reference_manifest`、IMAGE 批次 `images`，以及 `video_1`、`video_2`、`video_3`、`audio_1`、`audio_2`、`audio_3`。`generate` 新建，`rewrite` 保留剧情重写，`convert_storyboard` 接分镜转换，`audit` 只检查，`repair` 局部修复。

模式：T2VA 不接参考；I2VA 接 1 张首帧；FL2VA 接首尾 2 张；L2VA 接 1 张尾帧；Ref2VA 支持 Picture/Video/Audio（图片≤9、视频≤3、音频≤3、合计≤12）；R2V 是旧别名。

Ref2VA 任务示例：`<Picture 1> 保留人物身份与服装；<Video 1> 只参考奔跑节奏；<Audio 1> 在 Shot 2 保留脚步声。重演为雨夜车站追逐，8 秒。`

输出 `prompt` 接 H3 生成节点；`H3_PROMPT_PLAN` 是结构计划；`REFERENCE_MANIFEST` 是同步资产；`validation` 有 error 时不要继续；`warnings` 说明修复和回退。

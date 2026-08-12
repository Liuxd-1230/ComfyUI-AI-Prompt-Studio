# 模式与提示词示例

本页说明每个模式应该输入什么、会得到什么。示例只展示形态，不要求逐字照抄。

## LLM Generate

### history_mode

| 模式 | 期待输入 | 结果 |
|---|---|---|
| `append` | 连上上一轮 `CHAT_SESSION`，`user_prompt` 写新问题 | 保留历史并追加本轮 |
| `replace` | 连上旧 Session，但本轮要建立新上下文 | 返回只含本轮的新会话 |
| `off` | 单次生成 | 不读取也不累计历史 |

### output_mode

| 模式 | user_prompt 示例 | 期待输出 |
|---|---|---|
| `text` | `把这段剧情压缩成一句镜头描述` | 普通文本 |
| `json` | `输出 JSON：title 和 mood` | 可解析 JSON；不合格会 warning |
| `json_schema` | 同上，并在 `json_schema` 填对象 Schema | 端点实测支持时使用原生 Schema，否则提示词约束并校验 |

## Reference Analyzer 的 11 种 analysis_mode

| 模式 | text_anchor/custom_prompt 示例 | 期待提取 |
|---|---|---|
| `character_identity` | `角色名铃，成年女性` | 脸型、五官、发际线、稳定标记；不把服装当身份 |
| `character_full` | `铃，红色短发，身高约165cm` | 身份、体型、发型、服装、可见配饰 |
| `clothing` | `分析当前服装层次与材质` | 上装、下装、鞋、配饰、材质和颜色 |
| `pose_expression` | `分析动作与情绪，不猜身份` | 姿势、手势、视线、表情和瞬时状态 |
| `scene` | `这是室内咖啡店` | 地点、时间、天气、空间布局和可见物体 |
| `composition` | `分析构图` | 景别、机位、主体位置、透视和留白 |
| `style` | `分析画面风格` | 媒介、线条、上色、光照、色调；标为可变特征 |
| `object` | `主体是桌上的旧相机` | 物件形状、材质、结构、磨损和状态 |
| `anima_reference` | `为 ANIMA 提取可用视觉词` | 干净的二次元主体/风格信息，不混入 H3 运镜 |
| `h3_reference` | `为 H3 建立静态参考` | Subject/Picture 可观察属性，不从静态图虚构运动 |
| `custom` | custom_prompt：`只列出画面里能确认的食物及位置` | 严格按自定义任务，仍附“不猜测”守则 |

## Character Bible merge_strategy

| 模式 | 适用情况 | 冲突结果 |
|---|---|---|
| `manual_priority` | 已人工修订 existing_bible | 已有/锁定字段优先 |
| `text_priority` | 官方设定文字比图片可靠 | 文字覆盖冲突图片 |
| `image_priority` | 需要以当前参考图造型为准 | 图片候选优先 |
| `consensus` | 多来源相互校验 | 只提升一致项，冲突留报告 |
| `fill_missing_only` | 只补全空字段 | 绝不覆盖已有值 |

## Storyboard 模式

`split_mode=scene` 期待段落级剧情，输出每场一个条目；`shot` 期待可拍摄动作，输出镜头；`beat` 适合对白/动作节拍密集的短片；`auto` 让构建器按长度选择。`StoryboardSelect` 的 `scene/shot/range/all` 分别输出一场、一个镜头、序号区间或全部列表。

示例输入：`雨夜，铃冲进空车站寻找即将离开的朋友；广播响起，她在末班车关门前看见对方。` 不要在这里写 ANIMA 标签或 H3 六段格式。若已接 CharacterBook，角色书中的 ID、Speaker、stable/current 状态和来源会进入角色表；故事中新出现的人物要在 `character_definitions` 声明显示名，避免只剩 `char_02` 这种无法回看的编号。

Storyboard Builder 会在模型返回后确定性收敛：`max_scenes` 是硬上限，`target_duration` 会重新分配到全部镜头，重复或缺失 ID 会修复并在 `continuity` 报告；`audio` 可写在镜头或节拍上，之后可被 H3 转换消费。`StoryboardSelect` 的 scene 输出包含该场景的镜头摘要，shot 输出包含机位、时长、声音和节拍，适合直接接 Prompt Studio 或 H3。

## Image Prompt Studio

`execution_mode=lenient` 期待模型返回 `<PROMPT>完整目标提示词</PROMPT>` 与
`<SUMMARY>简短摘要</SUMMARY>`；适合普通创建和反复修改。`strict` 的 CREATE 使用
结构化 Plan，REFINE 使用 ChangeSet，适合需要字段级变更审计的任务。两者都不再使用
operation；Session 为空时创建，已有成功 Session 时修改。

### ANIMA Base / Aesthetic / Turbo

ANIMA 最终视觉提示词使用英文。中文可以作为 `text` 输入；两种执行模式都会检查最终视觉正文。角色名、专有名词、引用标签和引号内画面文字允许保留原文。

原始构想：`红发少女在雨夜车站回头，看见远处驶来的列车。`

Studio 当前统一期待完整 `natural_language` 成品，例如：`A red-haired young woman turns back on a rain-soaked station platform as an approaching train casts warm light through the blue night.`
`anima_aesthetic` 不使用 `score_*`；`anima_turbo` 可在摘要里说明 CFG 1、8–12 步建议。节点不固定注入 `safe`，也没有旧 tags/hybrid 或 safety operation。

### Z-Image Turbo

期待详细自然语言，不要 tag soup。输入可写：

```text
一名红色短发少女站在雨夜的旧式火车站月台中央，镜头略低于眼平，湿地反射暖黄色车灯；她刚刚回头，外套和发梢被风吹起。画面强调冷暖对比、真实雨丝和清晰面部。
```

输出应是连贯长描述，负面词为空。采样侧建议 9 步、CFG 0。

### Qwen-Image-Edit-2511

期待直接、可验证的编辑命令，并明确引用对象：

```text
保持 Figure 1 中人物的脸、发型和服装不变，把背景替换为雨夜火车站；使用 Figure 2 的蓝橙色灯光氛围。不要增加新人物。
```

先用 `APS_ReferencePrompt` 把 `@图1/@图2` 转成 `Figure 1/Figure 2` 并连接同一份 Manifest。不要写摄影散文替代编辑动作。

### Generic

`generic_image` 接受普通自然语言。第一次描述完整画面；后续直接写“只把光线改成冷色，人物和构图不变”一类修改意见。

## MiniMax H3 mode

H3 输入是“导演任务”。宽松模式直接维护完整官方文本，严格模式由 Plan 和渲染器生成；两者都不接受一半 JSON、一半六段文本。总时长只能 4–15 秒。

### T2VA · 纯文本

输入：`8 秒，一只橘猫从沙发跳到窗台，听见雷声后回头；写实家居，镜头缓慢推近。` 不连接参考资产。输出三字段，并包含镜头、同步声音与音乐策略。

### I2VA · 首帧锚定

连接 1 张 IMAGE。输入：`从首帧开始，女孩先保持静止，再抬头看向镜头；脸和服装保持一致。` 输出首帧对齐指令、`<Picture 1>` 生效位置和后续动作。

### FL2VA · 首尾帧路径

连接 2 张 IMAGE（首帧、尾帧）。输入：`从空旷站台自然过渡到女孩站在列车门前，中间经过一次跟拍，不要硬切。` 输出首尾约束与中间连续运动。

### L2VA · 尾帧收敛

连接 1 张尾帧 IMAGE。输入：`镜头从黑暗隧道向外移动，最终精确收敛到参考尾帧的构图。` 输出到达 `<Picture 1>` 的终点路径。

### Ref2VA · 图片/视频/音频全参考

输入应明确任务类型、每个资产保留什么以及在哪个 Shot 生效：

```text
角色重演。<Picture 1> 保留人物身份与服装；<Video 1> 只参考奔跑动作节奏；<Audio 1> 保留脚步声，在 Shot 2 生效。重新设计为雨夜车站追逐，8 秒。
```

输出六段：subject definitions、summary、retention analysis、detailed description、soundscape、music。图片≤9、视频≤3、音频≤3、合计≤12；视频总时长≤15 秒、音频总时长≤15 秒。

### R2V

旧工作流兼容别名，进入节点后迁移到 `Ref2VA`。新工作流请选择 Ref2VA。

## H3 继续修改

不再选择 operation。Session 为空时按 `text` 创建；已有成功 Session 时，`text` 只写本轮修改。
`session_action=previous` 恢复上一成功版本，`new` 在新 CREATE 成功后建立新 lineage。
`validation` 有 error 时节点不会提交该版本，也不应继续接生成节点。

## Runtime 模式

后端：`ollama` 使用 Ollama API；`llamacpp` 使用 llama.cpp server；`lmstudio` 使用 LM Studio v1/v0；`custom` 使用本扩展约定的兼容控制端点。动作：`status` 查询健康状态，`list_models` 列模型，`load/unload/reload` 操作指定模型，`unload_all` 只卸载当前已加载实例。

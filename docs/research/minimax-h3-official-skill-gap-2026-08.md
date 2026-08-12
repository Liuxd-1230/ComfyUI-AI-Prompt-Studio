# MiniMax H3 官方 Prompt Skill 差距复核

> 归档说明（2026-08-08，P6 更新）：这是迁移前的差距快照，不代表当前实现。所列主问题已进入 Model Core、代码、校验器和回归测试；本项目不再运行时加载 H3 Skill/YAML，当前限制以 `docs/known-limitations.md` 为准。

复核日期：2026-08-08。官方基线固定为 MiniMax-AI/MiniMax-H3 提交 [`8d8824e`](https://github.com/MiniMax-AI/MiniMax-H3/tree/8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea)。只采用 MiniMax 官方仓库及其中的官方 Skill、Prompt Guide 和示例；没有用社区教程推断规则。

## 结论

本仓库的总体架构方向正确：已经覆盖 T2VA、I2VA、FL2VA、L2VA 与全参考模式，并用结构化计划、确定性渲染、校验和一次修复实现了三字段/六段格式。首尾帧对齐句、镜头编号、三类媒体独立编号、稳定说话人、`<d>[Language]`、retention marker 和英语正文等主骨架与官方一致。

这份审计曾指出 Ref2VA 参考关系、镜头内音频和规则归属问题；P6 已把目标硬规则集中到不可编辑的 Model Core，并将用户可编辑内容改为受限 Markdown 补充资料。外部官方 Skill 链接仍作为可追溯研究依据，不是本项目运行时资产。

## P0：会产生错误或无效 H3 提示词

### 1. 镜头内声音被移到全局 soundscape

官方规定：与特定镜头同步的声音留在 `integrated_multimodal_description`/`detailed_description`，`overall_soundscape` 只总结全片环境声、物理声和非语言人声（[基础指南 §4.6](https://github.com/MiniMax-AI/MiniMax-H3/blob/8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea/skills/h3-prompt-writing/references/base-en.txt#L152-L157)，[Ref2VA §6](https://github.com/MiniMax-AI/MiniMax-H3/blob/8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea/skills/h3-prompt-writing/references/ref-en.txt#L280-L303)）。当前 `H3Shot.audio_notes` 声称是“本镜头内”声音，但 `render_shot()` 不输出它，`_soundscape_text()` 却把它追加到全局段，语义位置错误。应将同步声渲染进对应 Shot，并让 soundscape 只承担跨全片总结。

### 2. Ref2VA 引用关系在渲染时丢失

官方要求引用标签在六段中保持同一含义，并在首次出现及实际生效处插入；`<Picture N>`、`<Video N>`、`<Audio N>`各有不同角色（[标签定义](https://github.com/MiniMax-AI/MiniMax-H3/blob/8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea/skills/h3-prompt-writing/references/ref-en.txt#L24-L37)，[镜头内引用](https://github.com/MiniMax-AI/MiniMax-H3/blob/8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea/skills/h3-prompt-writing/references/ref-en.txt#L244-L256)）。当前计划虽然保存 `H3Shot.references`、`H3Subject.source_assets`、`H3Speaker.description`，但 renderer 均未消费；`subject_definitions` 也只额外输出 Audio 资产，独立 Picture/Video 定义会消失。LLM 若没有把标签重复写进自由描述，最终提示词就会出现“清单里有资产，正文没有引用”的情况。

### 3. 官方输入边界未执行

官方输出时长是 4–15 秒；Ref2VA 限制图片不超过 9、视频/音频各不超过 3、视频或音频单项及总时长有限制，音频不能作为唯一输入，混合文件总数不超过 12（[模型输入规格](https://github.com/MiniMax-AI/MiniMax-H3/blob/8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea/README.md#L62-L74)）。当前 Director 允许 `duration=0.5..600`，只直接接 IMAGE batch，manifest 中视频/音频数量和时长完全不校验。validator 也不知道目标时长，因此不能发现镜头切点越界。

### 4. `N/A` 的 soundscape 规则过宽

官方只在用户明确要求全片完全静音时允许 `overall_soundscape: N/A`，而没有非叙事配乐时才使用 `non_diegetic_music: N/A`（[官方规则](https://github.com/MiniMax-AI/MiniMax-H3/blob/8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea/skills/h3-prompt-writing/references/base-en.txt#L152-L165)）。当前 renderer 在 soundscape 为空时无条件写 `N/A`，可能把“LLM 漏写”误当成“用户要求静音”。

## P1：明显影响质量和官方一致性

### 1. 官方 Skill 没有进入可编辑 Skill 系统

官方 `h3-prompt-writing/SKILL.md` 是轻量入口，按模式路由到 `base-en.txt` 或 `ref-en.txt`，并明确要求保持字段名、顺序、标签和时序写法（[官方 Skill](https://github.com/MiniMax-AI/MiniMax-H3/blob/8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea/skills/h3-prompt-writing/SKILL.md#L8-L34)）。本仓库 H3 规则仍硬编码于 `services/h3_plan.py`，`skills/minimax_h3/` 为空，设置工作台无法查看、复制或定制。建议建立本项目自有的、注明官方来源与版本的 H3 Skill 包；协议硬约束仍留在 renderer/validator，Skill 管内容策略，不应只复制官方长文进每次请求。

### 2. 相机语言只是自由字符串

官方采用“运动类型 + 必要时的幅度 + 必要时的速度”，并区分 Zoom/Push、Pan/Truck、Tilt/Pedestal 等；相机运动应写成镜头内自然英语，而不是标签堆叠（[相机指南](https://github.com/MiniMax-AI/MiniMax-H3/blob/8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea/skills/h3-prompt-writing/references/base-en.txt#L94-L122)）。当前只有自由 `camera: str`，system prompt 没教这些差异，也没有词汇/冲突检查。镜头切换同样缺少“轻微景别变化优先运动、切镜应带来新信息”的规则（[Shots and Cuts](https://github.com/MiniMax-AI/MiniMax-H3/blob/8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea/skills/h3-prompt-writing/references/base-en.txt#L84-L92)）。

### 3. 对白连续性和画外音约束不完整

官方要求画外音的 `<d>` 后明确画面人物保持闭唇；跨切对白两边使用 `<scenetrans>`，片尾截断使用 `<cutoff>`（[对白规则](https://github.com/MiniMax-AI/MiniMax-H3/blob/8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea/skills/h3-prompt-writing/references/base-en.txt#L125-L142)）。当前 voiceover renderer 只有固定短语，没有闭唇说明；schema 无法表示跨切或截断。官方还要求画面文字放在英文双引号中并逐字保留（[On-Screen Text](https://github.com/MiniMax-AI/MiniMax-H3/blob/8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea/skills/h3-prompt-writing/references/base-en.txt#L144-L150)），当前只笼统说“保留原语言”。

### 4. Ref2VA 任务类型、详情密度和音频语义缺少约束

官方 summary 使用固定语义的任务类型组合：`keyframe completion`、`reference generation`、`video editing`、`video continuation`、`audio reuse`、`audio reference`，不能因“存在视频/音频”就自动选类型（[summary 规则](https://github.com/MiniMax-AI/MiniMax-H3/blob/8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea/skills/h3-prompt-writing/references/ref-en.txt#L121-L147)）。当前只检查 summary 以 `[` 开头，离线 storyboard 固定写 `[reference generation]`。官方生成类 Ref2VA 通常要求 350–500 个英文词，并逐镜头写构图、位置、光照、动作、状态、相机、声音和引用生效点（[详情规则](https://github.com/MiniMax-AI/MiniMax-H3/blob/8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea/skills/h3-prompt-writing/references/ref-en.txt#L209-L242)）；当前没有详情密度审计。

### 5. 时间戳边界与舍入存在缺口

官方要求后续镜头时间严格递增并落在目标时长内（[官方 Skill 输出规则](https://github.com/MiniMax-AI/MiniMax-H3/blob/8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea/skills/h3-prompt-writing/SKILL.md#L30-L34)）。当前只检查递增，不检查 `< duration`；`format_timestamp()` 在毫秒舍入到 1000 时强行改成 999，而不是向秒进位，边界值会被写错。

## P2：可用性与回归保障

- UI 使用旧称 `R2V`，官方公开仓库使用 `Ref2VA`。建议界面显示 `Ref2VA（兼容旧值 R2V）`，序列化层继续兼容旧工作流。
- 官方基础指南给出 T2VA/I2VA/FL2VA/L2VA 四个完整案例，Ref2VA 另有完整六段案例（[基础案例](https://github.com/MiniMax-AI/MiniMax-H3/blob/8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea/skills/h3-prompt-writing/references/base-en.txt#L168-L222)，[Ref2VA 完整案例](https://github.com/MiniMax-AI/MiniMax-H3/blob/8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea/skills/h3-prompt-writing/references/ref-en.txt#L305-L338)）。当前测试多为自造短例，未逐项锁定闭唇、跨切、截断、独立 Picture/Video 定义、镜头内音频和官方任务类型。建议把官方案例“提炼成不复制长文本的契约测试”，并加入上述失败用例。
- 官方仓库另带 8 个风格制作 Skill，但它们是端到端视频制作流程，不是 H3 核心提示词协议（[官方 Skills 目录说明](https://github.com/MiniMax-AI/MiniMax-H3/blob/8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea/skills/README.md#L1-L31)）。本节点包无需一次接完；先修核心 Prompt Skill 更有价值。

## 建议实施顺序

1. 修 renderer 的 `audio_notes`、`references`、Picture/Video 定义与 speaker 首现信息，并补 P0 回归测试。
2. 收紧 4–15 秒及 Ref2VA 媒体限制；validator 接收 duration/manifest，检查越界、未解析标签和错误资产角色。
3. 新建可编辑的 H3 Skill 入口与两份精简规则资源，在设置页展示来源版本；旧硬编码协议逐步缩为不可编辑的格式底线。
4. 增加相机词汇、画外音闭唇、`scenetrans`/`cutoff`、画面文字和 task-type schema；最后再补官方案例契约回归与中文帮助。

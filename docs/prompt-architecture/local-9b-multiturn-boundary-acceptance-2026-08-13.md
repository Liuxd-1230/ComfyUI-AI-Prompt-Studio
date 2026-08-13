# 本地 9B 多轮修改与边界实跑

## 环境与判定口径

- 日期：2026-08-13；LM Studio `http://127.0.0.1:1234/v1`
- 模型：`qwen3.5-9b-uncensored-hauhaucs-aggressive`（Q4_K_M）
- 档案：LM，`protocol=auto`、`reasoning=high`、`unload_policy=never`
- 路径：直接调用与 ComfyUI 相同的生产节点、Gateway、Schema、renderer 与
  validator；不连接图像/视频生成模型。
- “通过”同时要求节点不报错、validation 有效、Prompt 可直接下传、稳定事实未
  丢失、revision 正确递增。预期拒绝必须保持既有 Prompt/Plan/revision 不变。

这是按公开输入等价类覆盖的实跑，不声称穷举任意自然语言组合。确定性边界仍由
全量测试和 PH9 发布门覆盖。

## 多轮结果

### Image Prompt Studio

`anima_base + 宽松` 连续执行 CREATE → 改暖光 → 改近景，三轮均通过且无需修复，
revision 为 1/2/3。人物的黑色长卷发、琥珀绿色眼睛、象牙白玫瑰裙、黑色花卉腰带，
以及雨夜列车场景均保留。恢复 revision 2 会建立 revision 4；重复 nonce 返回 revision 3
且不调用模型。尝试修改锁定服装颜色会明确拒绝，这是正确的身份保护，不是失败。

初始 6 target × 2 execution mode 共 12 条真实 CREATE 中，宽松 6/6；严格模式暴露
ANIMA 字段重复所有权和字符串冒充数组。修正严格 Schema 字段职责并在反序列化边界
拒绝伪数组后，`anima_base` 严格 CREATE 可通过；本地 9B 的严格 ANIMA Turbo 与严格
多轮 ChangeSet 仍会随机产生重复 owner、错误路径或重复变更，因此失败会安全地不提交，
但不建议把严格模式作为该 9B 的默认路径。

### MiniMax H3 Prompt Studio

`T2VA + 宽松` 连续执行 CREATE → 加强车轮声 → 将 push-in 改为 truck-right，三轮均
通过且无需修复，revision 为 1/2/3；人物身份、动作、地点和无音乐约束保持不变。
恢复与重复 nonce 均为零模型调用。修复后 T2VA 宽松 CREATE 15.48 秒、严格 CREATE
30.17 秒通过。

最初 5 mode × 2 lane 的真实矩阵揭示了三类问题：自然英文插词被误判为身份缺失、
严格 Plan 未把锁定外观写入最终 Shot、闭合引用标签被当作未知引用。现已分别用有序
锚点匹配、权威 Character Bible 确定性注入、闭合标签规范化修复。I2VA/FL2VA/L2VA/
Ref2VA 的数量、总数、总时长、首帧/尾帧和引用规则由同一 validator 与全量回归覆盖；
本轮没有在修复后再次耗时重跑四种完整 live CREATE，不能将其记为新增现场绿灯。

## 其他公开模式

- Reference Analyzer：11/11 模式均能返回结构化结果；640.jpg 人物模式 34.86 秒，
  置信度 0.94，识别绿色眼睛、深棕长卷发、白色蕾丝服装、红玫瑰耳饰和腰饰。
  但非人物模式仍复用 Candidate 载体，偶有类别污染；这是语义质量限制，不算成高质量
  11/11。
- Storyboard Builder：scene/shot/beat/auto 4/4，均生成 1 场、3–4 镜头并可由
  Storyboard Select 读取。
- LLM Generate：text 的 append/replace/off、json 与 json_schema 组合最终 9/9。
  `json_schema + replace` 曾返回不可解析文本；现在只做一次 issue-only JSON 格式修复，
  真实复跑 1.54 秒得到 `{"location":"上海外滩","mood":"孤独"}`，零告警。

## 边界结论与推荐

实跑确认会拒绝：非法 execution mode、H3 低于 4 秒、各模式图片数量错误、Ref2VA
图片超过 9、媒体总数超过 12、仅音频参考、视频累计超过 15 秒和未知媒体时长。
现有回归另覆盖 stale revision、指纹变化、锁定事实改写、非英文 ANIMA、悬空引用、
坏 JSON、恢复与重复执行。

本地 9B 推荐使用“宽松”模式：多轮结果稳定、速度明显更快，且仍受确定性 validator、
锁定事实和 revision 事务保护。严格模式适合结构化能力更强的模型；在此 9B 上失败率
较高，但会拒绝提交而不会污染稳定版本。档案虽设置 `reasoning=high`，LM Studio 返回
未包含可观察的 reasoning 文本或 reasoning token，因此只能确认请求配置已开启，不能
声称服务端实际输出了可审计思考过程。

## 补充压力复核

同日继续按遗漏项补跑后，不再把单次绿灯当作稳定率：五个 H3 mode × 两条 lane
重复 CREATE 呈现明显随机性。第二轮中宽松 FL2VA/L2VA/Ref2VA 通过，T2VA/I2VA
被协议校验拒绝；严格 T2VA/FL2VA/Ref2VA 通过，I2VA/L2VA 被拒绝。严格 T2VA
还出现“validator 通过但丢失服装、玫瑰、动作和地点”的质量假绿，因此该 9B 的严格
结果不能仅凭 validation 判为可用。

宽松多轮重新按事实保持率检查：T2VA、I2VA、FL2VA、Ref2VA 均完成 CREATE、两次
局部修改、恢复与重复 nonce，并保留 dark hair、ivory Victorian rose dress、sunlit
stone conservatory、red rose、truck-right 五项事实；L2VA 首次因字段位置漂移拒绝，
随后加入只处理官方字段包装、不改变创意的确定性归一化。真实 Ref2VA 使用 640.jpg、
`visio.mp4` 的 6 秒裁剪和从其提取的 6 秒音频通过：Manifest 实测视频 5.99 秒、音频
6.00 秒，Picture/Video/Audio 均在成品中引用且 retention marker 模态正确。

压力测试还发现 SSE 只使用 read-timeout 时，服务端持续发送心跳或残片会使 120 秒设置
永不触发。Chat Completions 与 Responses 现共用原始 SSE 行级总截止时间；现场重试
不会再无限占住 ComfyUI 队列。宽松 H3 另对本地模型反复出现的方括号字段、XML 字段、
单数字分钟和缺失开标签做有限确定性归一化；镜头数、时间语义、引用关系和创意内容仍
交给 validator/模型修复，不会静默放宽。

Reference Analyzer 的 640.jpg 十一模式语义复核显示：人物身份、姿态、构图、风格、
ANIMA 与自定义颜色模式相关性较好；character_full/clothing 能看到服装细节但字段名
不稳定；scene/object/h3_reference 明显混入海报文字和人物属性。它们是“结构可运行”，
尚不是“模式语义纯净”。后续架构工作应为非人物模式采用各自结果 Schema，而不是继续
用 CharacterCandidate 表示场景、构图、物件和 H3 参考观察。

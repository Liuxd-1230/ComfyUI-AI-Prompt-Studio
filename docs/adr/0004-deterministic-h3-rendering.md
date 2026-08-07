# H3 提示词：LLM 生成结构化 plan + Python 确定性渲染，而非 LLM 直接写全文

H3 Director 采用：LLM 输出结构化 H3 plan（镜头/说话人/标签/声音/音乐）→ JSON Schema 校验 → Python renderer 确定性拼装三字段/六段与首行对齐指令 → 规则 validator 校验 → 可选一次模型修复。

官方手册对格式要求极严（首行指令、`[Shot N]` 时间戳、`<d>[Language]`、标签编号、retention markers），自由文本生成会高频踩规则。把格式拼装交给确定性代码，LLM 只负责内容决策，规则检查独立可测；「官方手册主要示例全部通过验证」成为可自动化的验收项。

## Considered Options

- LLM 直接输出最终提示词全文：省渲染代码，但格式违规率高，验收不可自动化。
- 纯模板：无法表达剧情内容，不满足生成/改写需求。

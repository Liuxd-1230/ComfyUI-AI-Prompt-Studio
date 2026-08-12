# Model Core 与 Markdown 补充资料

本工作单元移除运行时 Prompt Skill/YAML 注册表。目标模型硬规则只有一个不可编辑所有者：`prompting/model_cores.py`。目前已内置 ANIMA、Z-Image Turbo、Qwen Image Edit 2511、Generic Image 与 MiniMax H3 的核心规则；协议 Schema、renderer、validator、Diff Guard 和锁定事实继续由代码持有。

用户资料改用本地 Markdown supplement。设置工作台通过 `/supplements` 管理资料的导入、查看、编辑、启停和删除；每份资料保存文件名、范围、目标族/节点、大小、SHA-256 和更新时间。单份资料不超过 256 KiB，每次最多激活 8 份、总上下文不超过 128 KiB。节点的 `prompt_supplements` 输入支持逗号分隔的显式 ID；目标 Studio 也支持 `auto` 选择当前目标启用资料，通用 LLM 只接受显式 ID，避免隐藏上下文。

资料会作为带 `<document>` 来源标记的 `SUPPLEMENT` 层进入 Prompt Assembly，并明确声明“只能提供参考”。它不能改变 Model Core、Runtime Policy、输出 Schema、用户最新请求、锁定约束或 validator。Session fingerprint 记录 supplement hash；资料被编辑、停用或换绑时，下次已绑定会话先报告上下文变化，而不是静默继续。

验证：

```bash
python -m pytest tests/test_supplements.py tests/test_smoke_routes.py tests/test_prompt_audit.py -q
node --check web/settings.js
```

旧 `services/skills.py`、仓库 YAML Skill 和 `/skills` 路由已删除。MiniMax-H3 官方仓库中的 `skills/` 仍只是外部研究来源，不是本项目运行时插件。

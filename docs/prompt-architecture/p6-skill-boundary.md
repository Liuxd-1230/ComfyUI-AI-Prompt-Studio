# Skill Guidance Boundary

本工作单元收口 Persistent contract §108.26。`APS_PromptStudio` 与
`APS_H3PromptStudio` 的 Runtime Policy、目标 Model Core、输出协议、validator、
Diff Guard 和锁定事实由仓库代码持有，不能被可编辑 Skill 替换。

Skill 仍可提供目标相关的软创作建议，但传输方式固定为：

```text
SYSTEM
  immutable Runtime boundary + Model Core + operation policy

TASK DATA
  external_skill_guidance {
    id, version, target, source, content_hash, guidance
  }

USER
  latest instruction
```

Runtime boundary 明确忽略 Skill 中的“忽略前文”、改输出格式、关闭校验、索取密钥/工具或跨模型规则。Session fingerprint 同时记录 Skill hash；Skill 被编辑、启停或替换时，已有 Session 会在下一轮先报上下文变化，不会静默套用新规则。

回归测试 `tests/test_skill_security.py` 通过两个公开 Studio 节点注入恶意自定义 Skill，验证恶意文本不进入 system policy、只出现在标记 task-data 中，且成品仍按原协议提交。验证命令：

```bash
python -m pytest tests/test_skill_security.py tests/test_prompt_studio.py tests/test_h3_prompt_studio.py -q
```

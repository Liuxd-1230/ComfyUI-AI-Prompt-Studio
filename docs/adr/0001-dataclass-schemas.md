# Schema 采用 dataclass 而非 pydantic

节点间传递的 12 种数据类型用标准库 dataclass（含 schema_version、迁移注册表、JSON 导入导出、输入容错），不依赖 pydantic。

ComfyUI venv 里有 pydantic v2，但测试在系统 Python 3.13.11 上跑（无 pydantic）。用 dataclass 让运行环境与测试环境保持零第三方依赖一致，并把校验逻辑显式写在 migration/`from_json` 中，错误信息可控。pydantic 带来的自动校验收益在这个规模下不足以抵消环境分裂成本。

## Considered Options

- pydantic v2：venv 可用但测试环境未装，需额外安装或分裂。
- 裸 dict：失去结构约束，被规范明确禁止。

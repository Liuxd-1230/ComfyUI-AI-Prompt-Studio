"""Lossless semantic plan for prose-oriented image prompt families."""
import dataclasses
from typing import Any

from .base import Schema, SchemaError


@dataclasses.dataclass
class PromptClause(Schema):
    text: str = ""
    separator: str = ""


@dataclasses.dataclass
class TextPromptPlan(Schema):
    clauses: list[PromptClause] = dataclasses.field(default_factory=list)

    @classmethod
    def from_json(cls, data: Any) -> "TextPromptPlan":
        if isinstance(data, dict) and "body" in data and "clauses" not in data:
            data = {"clauses": [{"text": str(data.get("body", "")), "separator": ""}]}
        plan = super().from_json(data)
        if not isinstance(plan, cls):
            raise SchemaError("TextPromptPlan: 无法构造")
        if not isinstance(plan.clauses, list) or any(
                not isinstance(item, PromptClause) for item in plan.clauses):
            raise SchemaError("TextPromptPlan.clauses 必须是结构化分句列表")
        return plan

    def render(self) -> str:
        return "".join(item.text + item.separator for item in self.clauses)

    def to_json(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version,
                "clauses": [{"text": item.text, "separator": item.separator}
                            for item in self.clauses]}

    def to_llm_context(self) -> dict[str, Any]:
        return {"clauses": [{"text": item.text, "separator": item.separator}
                            for item in self.clauses]}

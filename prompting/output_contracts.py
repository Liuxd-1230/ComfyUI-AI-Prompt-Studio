"""Machine-owned output contracts for every LLM response shape."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .assembly import PromptLayer, PromptSource


class OutputKind(str, Enum):
    TEXT = "text"
    TAGGED_PROMPT = "tagged_prompt"
    JSON_OBJECT = "json_object"
    JSON_SCHEMA = "json_schema"


@dataclass(frozen=True)
class OutputContract:
    """One response contract shared by assembly, Gateway, and diagnostics."""

    contract_id: str
    version: str
    kind: OutputKind
    schema: dict[str, Any] | None = None
    summary: str = ""

    def __post_init__(self) -> None:
        if not self.contract_id.strip() or not self.version.strip():
            raise ValueError("OutputContract 需要非空 contract_id/version")
        if self.kind is OutputKind.JSON_SCHEMA:
            if not isinstance(self.schema, dict) or not self.schema:
                raise ValueError("JSON_SCHEMA OutputContract 需要机器可读 schema")
        elif self.schema is not None:
            raise ValueError(f"{self.kind.value} OutputContract 不接受 schema")

    @property
    def identifier(self) -> str:
        return f"{self.contract_id}@{self.version}"

    @property
    def wants_json(self) -> bool:
        return self.kind in {OutputKind.JSON_OBJECT, OutputKind.JSON_SCHEMA}

    def source(self, *, scope: str) -> PromptSource:
        return PromptSource(
            source_id=f"output.{self.contract_id}",
            version=self.version,
            layer=PromptLayer.OUTPUT_CONTRACT,
            content=self.summary or self._default_summary(),
            scope=scope,
        )

    def native_schema(self) -> dict[str, Any] | None:
        return copy.deepcopy(self.schema)

    def fallback_instruction(self) -> str:
        """Derive non-native JSON guidance from the same machine contract."""
        if self.kind is OutputKind.JSON_SCHEMA:
            schema_text = json.dumps(
                self.schema, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            )
            return (
                "Return exactly one valid JSON object and no Markdown or commentary. "
                "It must satisfy this machine-owned JSON Schema:\n" + schema_text
            )
        if self.kind is OutputKind.JSON_OBJECT:
            return "Return exactly one valid JSON object and no Markdown or commentary."
        return ""

    def _default_summary(self) -> str:
        if self.kind is OutputKind.JSON_SCHEMA:
            return "Return exactly one JSON object matching the attached machine schema."
        if self.kind is OutputKind.JSON_OBJECT:
            return "Return exactly one valid JSON object, with no surrounding prose."
        if self.kind is OutputKind.TAGGED_PROMPT:
            return (
                "Return one complete target-ready prompt inside <PROMPT>...</PROMPT> "
                "and one short factual summary inside <SUMMARY>...</SUMMARY>. Return no "
                "JSON, Markdown fences, schema explanation, analysis, or alternatives."
            )
        return self.summary


def schema_contract(contract_id: str, schema: dict[str, Any], *,
                    version: str = "1.0", summary: str = "") -> OutputContract:
    return OutputContract(contract_id, version, OutputKind.JSON_SCHEMA,
                          copy.deepcopy(schema), summary)


def json_object_contract(contract_id: str = "json-object", *,
                         version: str = "1.0") -> OutputContract:
    return OutputContract(contract_id, version, OutputKind.JSON_OBJECT)


LENIENT_PROMPT_CONTRACT = OutputContract(
    "lenient-tagged-prompt",
    "1.0",
    OutputKind.TAGGED_PROMPT,
    summary=(
        "Return only this lightweight envelope:\n"
        "<PROMPT>\nthe complete target-ready prompt\n</PROMPT>\n"
        "<SUMMARY>\none short factual summary of what you created or changed\n</SUMMARY>\n"
        "Do not return JSON, Markdown fences, schema explanations, analysis, or "
        "alternatives. The PROMPT block must be complete and directly usable by the "
        "target model."
    ),
)

"""Deterministic six-layer prompt compiler with provenance reporting."""
from __future__ import annotations

import dataclasses
import hashlib
import json
from enum import IntEnum
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    from .output_contracts import OutputContract


class PromptLayer(IntEnum):
    RUNTIME = 10
    NODE_CORE = 20
    MODEL_CORE = 30
    OPERATION = 40
    SUPPLEMENT = 50
    OUTPUT_CONTRACT = 60


@dataclasses.dataclass(frozen=True)
class PromptSource:
    source_id: str
    version: str
    layer: PromptLayer
    content: str
    scope: str = "global"

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


@dataclasses.dataclass(frozen=True)
class StructuredTaskData:
    data_id: str
    value: Any
    media_type: str = "application/json"

    def render(self) -> str:
        if self.media_type == "text/plain":
            body = str(self.value)
        else:
            body = json.dumps(self.value, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"))
        return f"<task-data id={json.dumps(self.data_id)}>\n{body}\n</task-data>"


@dataclasses.dataclass(frozen=True)
class PromptAssemblyReport:
    sources: tuple[dict[str, str], ...]
    task_data_ids: tuple[str, ...]
    output_contract_id: str
    assembly_hash: str


@dataclasses.dataclass(frozen=True)
class PromptAssembly:
    system: str
    task_data: str
    report: PromptAssemblyReport
    output_contract: OutputContract | None = None


class PromptAssembler:
    """Compile owned sources and labelled data without role promotion."""

    def assemble(self, sources: Iterable[PromptSource],
                 task_data: Iterable[StructuredTaskData], *,
                 latest_user: str = "", output_contract_id: str = "") -> PromptAssembly:
        ordered = sorted(sources, key=lambda source: (source.layer, source.source_id))
        source_ids = [source.source_id for source in ordered]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Prompt source_id 重复，无法确定所有权")
        system = "\n\n".join(
            f"[{source.layer.name}:{source.source_id}@{source.version}]\n{source.content.strip()}"
            for source in ordered if source.content.strip())
        data_items = list(task_data)
        rendered_data = [item.render() for item in data_items]
        if latest_user.strip():
            rendered_data.append(StructuredTaskData(
                "latest_user", latest_user, "text/plain").render())
        task_text = "\n\n".join(rendered_data)
        provenance = tuple({
            "source_id": source.source_id,
            "version": source.version,
            "layer": source.layer.name,
            "scope": source.scope,
            "hash": source.content_hash,
        } for source in ordered)
        digest_input = json.dumps({
            "sources": provenance,
            "system": system,
            "task_data": task_text,
            "output_contract_id": output_contract_id,
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        report = PromptAssemblyReport(
            sources=provenance,
            task_data_ids=tuple(item.data_id for item in data_items)
                          + (("latest_user",) if latest_user.strip() else ()),
            output_contract_id=output_contract_id,
            assembly_hash=hashlib.sha256(digest_input.encode("utf-8")).hexdigest(),
        )
        return PromptAssembly(system=system, task_data=task_text, report=report)

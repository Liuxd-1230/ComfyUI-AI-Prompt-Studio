"""Small integration helpers for node-to-provider prompt assembly."""
from __future__ import annotations

import dataclasses
from typing import Any, Iterable

from ..schemas.results import ChatMessage
from .assembly import (PromptAssembler, PromptAssembly, PromptSource,
                       StructuredTaskData)


def assemble_prompt(sources: Iterable[PromptSource], *,
                    task_data: Iterable[StructuredTaskData] = (),
                    output_contract_id: str = "") -> PromptAssembly:
    return PromptAssembler().assemble(
        sources, task_data, output_contract_id=output_contract_id)


def task_message(assembly: PromptAssembly) -> ChatMessage:
    if not assembly.task_data:
        raise ValueError("Prompt assembly 没有结构化任务数据")
    return ChatMessage(role="user", content=assembly.task_data)


def report_payload(assembly: PromptAssembly) -> dict[str, Any]:
    return dataclasses.asdict(assembly.report)

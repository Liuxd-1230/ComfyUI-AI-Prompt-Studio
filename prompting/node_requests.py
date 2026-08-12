"""Small integration helpers for node-to-provider prompt assembly."""
from __future__ import annotations

import dataclasses
from typing import Any, Iterable

from ..schemas.results import ChatMessage
from .assembly import (PromptAssembler, PromptAssembly, PromptSource,
                       StructuredTaskData)
from .output_contracts import OutputContract


def assemble_prompt(sources: Iterable[PromptSource], *,
                    task_data: Iterable[StructuredTaskData] = (),
                    output_contract: OutputContract | None = None) -> PromptAssembly:
    owned_sources = list(sources)
    if output_contract is not None:
        owned_sources.append(output_contract.source(scope="prompt-assembly"))
    assembly = PromptAssembler().assemble(
        owned_sources, task_data,
        output_contract_id=(output_contract.identifier
                            if output_contract is not None else ""))
    return dataclasses.replace(assembly, output_contract=output_contract)


def task_message(assembly: PromptAssembly) -> ChatMessage:
    if not assembly.task_data:
        raise ValueError("Prompt assembly 没有结构化任务数据")
    return ChatMessage(role="user", content=assembly.task_data)


def report_payload(assembly: PromptAssembly) -> dict[str, Any]:
    return dataclasses.asdict(assembly.report)

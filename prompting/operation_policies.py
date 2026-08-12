"""Versioned operation policies shared by every creative LLM call.

Target rules belong to Model Core, task facts belong to structured task data,
and transport shapes belong to output schemas.  This module owns only what the
model is doing *this turn*.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .assembly import PromptLayer, PromptSource


class OperationKind(str, Enum):
    CREATE = "create"
    REFINE = "refine"
    FORMAT_REPAIR = "format_repair"
    PROTOCOL_RETRY = "protocol_retry"
    OBSERVE_TEXT = "observe_text"
    OBSERVE_IMAGE = "observe_image"


@dataclass(frozen=True)
class OperationPolicy:
    """One repository-owned policy at the operation seam."""

    kind: OperationKind
    version: str
    content: str


_POLICIES = {
    OperationKind.CREATE: OperationPolicy(
        OperationKind.CREATE,
        "1.0",
        "Create one complete result from the latest request and supplied source "
        "state. Preserve every explicit identity, count, relationship, action, "
        "composition, and reference requirement. Do not invent contradictory facts.",
    ),
    OperationKind.REFINE: OperationPolicy(
        OperationKind.REFINE,
        "2.0",
        "Treat the latest request as a delta against the supplied current state. "
        "Identify only requested changes and necessary consistency dependencies. "
        "Preserve every unrelated decision; do not improve or rewrite unrelated content.",
    ),
    OperationKind.FORMAT_REPAIR: OperationPolicy(
        OperationKind.FORMAT_REPAIR,
        "1.0",
        "Repair only the concrete reported protocol, format, or target-language issues "
        "in the rejected "
        "output. Preserve all usable meaning and facts. Do not add creative details, "
        "redesign the request, or change unrelated content. If a language issue is "
        "listed, translate only the cited prose while preserving names, reference "
        "labels, dialogue, lyrics, and quoted on-screen text.",
    ),
    OperationKind.PROTOCOL_RETRY: OperationPolicy(
        OperationKind.PROTOCOL_RETRY,
        "1.0",
        "The previous response failed the declared output contract. Retry exactly once, "
        "correcting only the listed protocol defects. Return only the declared output "
        "shape and preserve all usable facts from the rejected response.",
    ),
    OperationKind.OBSERVE_TEXT: OperationPolicy(
        OperationKind.OBSERVE_TEXT,
        "1.0",
        "Extract only facts stated in the supplied text into the declared observation "
        "schema. Mark uncertainty explicitly and do not add unstated visual facts.",
    ),
    OperationKind.OBSERVE_IMAGE: OperationPolicy(
        OperationKind.OBSERVE_IMAGE,
        "1.0",
        "Record only observable image evidence in the declared observation schema. "
        "Do not infer hidden identity, intent, history, or unsupported attributes.",
    ),
}


def operation_source(kind: OperationKind, *, scope: str) -> PromptSource:
    """Return the sole PromptSource interface for a runtime operation policy."""
    policy = _POLICIES[kind]
    return PromptSource(
        source_id=f"operation.{kind.value}",
        version=policy.version,
        layer=PromptLayer.OPERATION,
        content=policy.content,
        scope=scope,
    )


def operation_policy(kind: OperationKind) -> OperationPolicy:
    """Expose immutable policy metadata for fingerprints and contract tests."""
    return _POLICIES[kind]

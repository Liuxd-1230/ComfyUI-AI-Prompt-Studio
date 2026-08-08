"""JSON Schema helpers shared by every structured-output producer."""
from __future__ import annotations

from typing import Any, Dict


def make_strict_schema(node: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize every nested object for OpenAI-style strict JSON Schema.

    Strict endpoints require ``additionalProperties=false`` and require every
    declared property. Optional application fields remain representable with
    empty strings/arrays or nullable types in the schema itself.
    """
    if node.get("type") == "object":
        properties = node.get("properties", {})
        node["additionalProperties"] = False
        node["required"] = list(properties)
        for value in properties.values():
            if isinstance(value, dict):
                make_strict_schema(value)
    if node.get("type") == "array" and isinstance(node.get("items"), dict):
        make_strict_schema(node["items"])
    return node

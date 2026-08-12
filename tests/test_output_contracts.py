"""PH6 machine-owned Output Contract interface regressions."""
from __future__ import annotations

import pytest

from aps.prompting.assembly import PromptLayer
from aps.prompting.output_contracts import (
    LENIENT_PROMPT_CONTRACT,
    OutputContract,
    OutputKind,
    json_object_contract,
    schema_contract,
)


def test_schema_contract_owns_id_source_schema_and_fallback() -> None:
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}
    contract = schema_contract("person", schema, version="2.0")

    assert contract.identifier == "person@2.0"
    assert contract.source(scope="test").layer is PromptLayer.OUTPUT_CONTRACT
    assert contract.native_schema() == schema
    assert '"name":{"type":"string"}' in contract.fallback_instruction()

    returned = contract.native_schema()
    returned["type"] = "array"
    assert contract.native_schema()["type"] == "object"


def test_non_schema_contract_cannot_smuggle_a_second_schema() -> None:
    with pytest.raises(ValueError, match="不接受 schema"):
        OutputContract("text", "1", OutputKind.TEXT, {"type": "object"})


def test_tagged_and_json_contracts_expose_their_real_protocol() -> None:
    assert "<PROMPT>" in LENIENT_PROMPT_CONTRACT.source(scope="x").content
    contract = json_object_contract()
    assert contract.wants_json
    assert contract.native_schema() is None
    assert "exactly one valid JSON object" in contract.fallback_instruction()

"""PH5 operation-policy interface and lifecycle ownership regressions."""
from __future__ import annotations

from pathlib import Path

from aps.prompting.assembly import PromptLayer
from aps.prompting.operation_policies import (
    OperationKind,
    operation_policy,
    operation_source,
)


ROOT = Path(__file__).resolve().parents[1]


def test_every_runtime_operation_has_one_versioned_source() -> None:
    for kind in OperationKind:
        policy = operation_policy(kind)
        source = operation_source(kind, scope="test")
        assert policy.content.strip()
        assert source.source_id == f"operation.{kind.value}"
        assert source.version == policy.version
        assert source.layer is PromptLayer.OPERATION
        assert source.scope == "test"


def test_refine_and_repair_have_disjoint_responsibilities() -> None:
    refine = operation_policy(OperationKind.REFINE).content
    repair = operation_policy(OperationKind.FORMAT_REPAIR).content
    assert "latest request as a delta" in refine
    assert "Preserve every unrelated decision" in refine
    assert "concrete reported protocol" in repair
    assert "Do not add creative details" in repair


def test_legacy_user_operation_surfaces_are_removed() -> None:
    prompt_plan = (ROOT / "schemas" / "prompt_plan.py").read_text(encoding="utf-8")
    h3_plan = (ROOT / "schemas" / "h3.py").read_text(encoding="utf-8")
    h3_service = (ROOT / "services" / "h3_plan.py").read_text(encoding="utf-8")
    assert "COMPOSER_OPERATIONS" not in prompt_plan
    assert "H3_OPERATIONS" not in h3_plan
    assert "def build_plan_prompt" not in h3_service
    assert "def convert_storyboard" not in h3_service


def test_production_does_not_construct_private_operation_sources() -> None:
    for folder in ("nodes", "services"):
        for path in (ROOT / folder).rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert 'PromptSource("operation.' not in source, path

"""Static P0 gates for prompt-call ownership and architecture documents."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs" / "prompt-architecture" / "prompt-inventory.md"


def _call_lines(relative: str, pattern: str) -> list[int]:
    text = (ROOT / relative).read_text(encoding="utf-8")
    return [text.count("\n", 0, match.start()) + 1
            for match in re.finditer(pattern, text)]


def test_every_creative_gateway_call_has_an_inventory_owner() -> None:
    expected = {
        "nodes/llm_chat.py": ("llm.generate", 1),
        "nodes/reference_analyzer.py": ("reference.text", 1),
        "nodes/storyboard_builder.py": ("storyboard.create", 1),
        "nodes/prompt_composer.py": ("composer.render", 1),
        "services/prompt_session.py": ("session.refine", 1),
        "nodes/minimax_h3_director.py": ("h3.create", 2),
    }
    inventory = INVENTORY.read_text(encoding="utf-8")
    for relative, (owner, count) in expected.items():
        lines = _call_lines(relative, r"(?:Gateway\(\)|gateway)\.generate\(")
        assert len(lines) == count, f"Update inventory for {relative}: {lines}"
        assert f"`{owner}`" in inventory


def test_every_direct_vision_call_has_an_inventory_owner() -> None:
    lines = _call_lines("nodes/reference_analyzer.py", r"vision_svc\.call_vision\(")
    inventory = INVENTORY.read_text(encoding="utf-8")
    assert len(lines) == 2, f"Update inventory for vision calls: {lines}"
    assert "`reference.image`" in inventory
    assert "`reference.identity`" in inventory


def test_p0_architecture_deliverables_are_substantive() -> None:
    required = [
        INVENTORY,
        ROOT / "docs" / "prompt-architecture" / "prompt-ownership.md",
        ROOT / "docs" / "prompt-architecture" / "current-state-audit-p0.md",
        ROOT / "docs" / "adr" / "0006-semantic-and-prompt-architecture-boundaries.md",
    ]
    for path in required:
        text = path.read_text(encoding="utf-8")
        assert len(text) > 900, path
        assert "placeholder" not in text.lower()

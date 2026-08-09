from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_official_ledger_covers_all_supported_priority_targets() -> None:
    ledger = (ROOT / "docs" / "prompt-architecture" /
              "official-source-ledger.md").read_text(encoding="utf-8")
    for target in ("ANIMA", "Z-Image Turbo", "Qwen Image Edit 2511", "MiniMax H3"):
        assert target in ledger
    assert "8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea" in ledger
    assert "Community posts" in ledger and "excluded" in ledger


def test_each_target_has_substantive_evidence_and_local_diff() -> None:
    notes = [
        ROOT / "docs" / "prompt-sources" / "anima" / "official-review-2026-08.md",
        ROOT / "docs" / "prompt-sources" / "z-image-turbo" / "official-review-2026-08.md",
        ROOT / "docs" / "prompt-sources" / "qwen-image-edit-2511" / "official-review-2026-08.md",
        ROOT / "docs" / "prompt-sources" / "minimax-h3" / "official-review-2026-08.md",
    ]
    for note in notes:
        text = note.read_text(encoding="utf-8")
        assert len(text) > 1200, note
        assert "Primary source" in text
        assert "Local Diff" in text
        assert "placeholder" not in text.lower()

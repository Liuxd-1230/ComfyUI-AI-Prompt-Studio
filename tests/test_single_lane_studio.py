"""Public contract for the single-lane Prompt Studio migration."""
from __future__ import annotations

import pytest

from aps.nodes.h3_prompt_studio import APS_H3PromptStudio
from aps.nodes.prompt_studio import APS_PromptStudio
from aps.schemas.prompt_session import PromptSession
from aps.nodes.prompt_studio import (
    _explicit_negative_constraints,
    _negative_for,
)
from aps.validators.minimax_h3 import validate_h3


@pytest.mark.parametrize("node", [APS_PromptStudio, APS_H3PromptStudio])
def test_studio_public_input_has_no_execution_mode(node) -> None:
    inputs = node.INPUT_TYPES()

    assert "execution_mode" not in inputs["required"]
    assert "execution_mode" not in inputs.get("optional", {})


def test_new_sessions_use_single_lane_identity() -> None:
    session = PromptSession()

    assert session.execution_mode == "single"


def test_legacy_strict_session_requires_new_session() -> None:
    payload = PromptSession().to_json()
    payload["schema_version"] = "3.1"
    payload["execution_mode"] = "strict"

    with pytest.raises(ValueError, match="旧 strict.*新会话"):
        PromptSession.from_json(payload)


def test_anima_single_lane_restores_quality_prefix_and_explicit_negatives() -> None:
    negative = _negative_for(
        "anima", "base", "Create a portrait. Avoid watermark, extra fingers")

    assert "score_1" in negative
    assert "watermark, extra fingers" in negative


def test_negative_extraction_does_not_guess_from_ordinary_scene_text() -> None:
    assert _explicit_negative_constraints(
        "A woman without an umbrella walks through rain") == []


def test_h3_rejects_non_audible_sensory_claim_in_soundscape() -> None:
    prompt = (
        "integrated_multimodal_description: [Shot 1] A woman waits.\n"
        "overall_soundscape: Rain falls; the air smells of old paper.\n"
        "non_diegetic_music: N/A")

    report = validate_h3(prompt, "T2VA", duration=6.0)

    assert not report.valid
    assert any(issue.code == "h3_soundscape_non_audible"
               for issue in report.issues)

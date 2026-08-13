"""Executable coverage contract for supported public prompt-workflow combinations."""
from __future__ import annotations

import json
from pathlib import Path

import aps
from aps.nodes.character_bible import APS_CharacterBible, MERGE_STRATEGIES
from aps.nodes.prompt_studio import TARGET_OPTIONS
from aps.nodes.reference_analyzer import MODE_PROMPTS, _PROMPT_GUARDRAIL
from aps.nodes.storyboard_select import APS_StoryboardSelect
from aps.schemas.character import CharacterBible, CharacterCandidate, CharacterTrait
from aps.schemas.h3 import H3_UI_MODES
from aps.schemas.references import ANALYSIS_MODES
from aps.schemas.storyboard import SELECT_MODES, SPLIT_MODES
from aps.services.storyboard import fallback_storyboard


CATALOG = Path(__file__).resolve().parent.parent / "examples" / "acceptance" / "prompt_matrix.json"


def _catalog() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def test_acceptance_catalog_covers_every_public_mode() -> None:
    data = _catalog()
    assert set(data["image_studio"]) == set(TARGET_OPTIONS)
    assert set(data["h3_studio"]) == set(H3_UI_MODES)
    assert set(data["reference_analysis"]) == set(ANALYSIS_MODES)
    assert set(data["character_merge"]) == set(MERGE_STRATEGIES)
    assert set(data["storyboard_split"]) == set(SPLIT_MODES)
    assert set(data["storyboard_select"]) == set(SELECT_MODES)
    assert set(data["llm_output"]) == {"text", "json", "json_schema"}
    assert set(data["llm_history"]) == {"append", "replace", "off"}


def test_acceptance_catalog_has_prompt_and_effect_for_every_live_case() -> None:
    cases = _catalog()["live_cases"]
    assert cases
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids))
    for case in cases:
        assert case["prompt"].strip()
        assert case["expected_effect"].strip()
        assert case["expected_checks"]
        assert case["status"] in {"required", "passed", "blocked"}
        if case["status"] == "passed":
            evidence = case.get("evidence", {})
            assert evidence.get("run_type")
            assert evidence.get("result")


def test_every_reference_analysis_mode_has_an_executable_instruction() -> None:
    for mode in ANALYSIS_MODES:
        if mode == "custom":
            continue
        instruction = MODE_PROMPTS[mode]
        assert instruction.strip()
        assert _PROMPT_GUARDRAIL in instruction
    assert MODE_PROMPTS["custom"] == ""


def test_every_character_merge_strategy_executes() -> None:
    existing = CharacterBible(character_id="rose", name="Rose", traits=[
        CharacterTrait(name="hair", value="black hair", locked=True)])
    candidate = CharacterCandidate(name="Rose", traits=[
        CharacterTrait(name="hair", value="brown hair", sources=["image:0"]),
        CharacterTrait(name="eyes", value="amber eyes", sources=["image:0"])])
    for strategy in MERGE_STRATEGIES:
        bible, prompt, *_ = APS_CharacterBible().merge(
            strategy, character_candidate=candidate.to_json(),
            existing_bible=existing.to_json(), character_name="Rose")
        restored = CharacterBible.from_json(bible)
        assert restored.character_id == "rose"
        assert restored.trait_map()["hair"].value == "black hair"
        assert prompt.strip()


def test_every_storyboard_split_and_select_mode_executes() -> None:
    boards = {
        mode: fallback_storyboard(
            "Rose opens a blank letter in a train carriage.", mode,
            target_duration=8.0)
        for mode in SPLIT_MODES
    }
    for mode, board in boards.items():
        assert board.split_mode == mode
        assert board.scenes and board.scenes[0].shots
    board = boards["shot"]
    inputs = {
        "scene": ("1", "", ""),
        "shot": ("", "1", ""),
        "range": ("", "", "1-1"),
        "all": ("", "", ""),
    }
    for mode, (scene_id, shot_id, range_text) in inputs.items():
        item, items, scene_text, _, count, batch = APS_StoryboardSelect().select(
            board.to_json(), mode, scene_id, shot_id, range_text)
        assert item and items and scene_text.strip()
        assert count >= 1 and batch


def test_all_custom_type_connections_are_declared_in_catalog() -> None:
    data = _catalog()
    declared = {tuple(edge) for edge in data["connections"]}
    produced: dict[str, list[tuple[str, str]]] = {}
    consumed: dict[str, list[tuple[str, str]]] = {}
    custom = {value for value in aps.schemas.types._SCHEMA_IMPORTS}
    for node_name, cls in aps.NODE_CLASS_MAPPINGS.items():
        for output_name, output_type in zip(cls.RETURN_NAMES, cls.RETURN_TYPES):
            if output_type in custom:
                produced.setdefault(output_type, []).append((node_name, output_name))
        inputs = cls.INPUT_TYPES()
        for group in ("required", "optional"):
            for input_name, spec in inputs.get(group, {}).items():
                input_type = spec[0]
                if isinstance(input_type, str) and input_type in custom:
                    consumed.setdefault(input_type, []).append((node_name, input_name))
    discovered = {
        (source_node, source_port, target_node, target_port, type_name)
        for type_name, sources in produced.items()
        for source_node, source_port in sources
        for target_node, target_port in consumed.get(type_name, [])
        if source_node != target_node or source_port != target_port
    }
    assert declared == discovered

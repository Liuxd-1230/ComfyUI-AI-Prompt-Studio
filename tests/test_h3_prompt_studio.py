"""H3 Prompt Studio behavior through its public Comfy node interface."""
from __future__ import annotations

import json

import pytest

import aps.nodes.h3_prompt_studio as studio_mod
from aps.schemas.character import CharacterBible, CharacterTrait
from aps.schemas.prompt_session import PromptSession
from aps.schemas.results import LLMResult


def _profile(store):
    store.create_profile({"profile_id": "h3-studio", "name": "H3 Studio"})
    store.set_api_key("h3-studio", "lm-studio-local")
    return store.get_profile("h3-studio").node_payload()


class SequenceGateway:
    responses: list[str] = []
    requests: list[object] = []

    def generate(self, profile, api_key, request):
        del profile, api_key
        type(self).requests.append(request)
        return LLMResult(text=type(self).responses.pop(0))


PLAN = {
    "style_opening": "", "summary": "", "speakers": [], "subjects": [],
    "assets": [], "retention": [], "soundscape": "Rain falls on the roof.",
    "non_diegetic_music": "N/A", "explicit_silence": False,
    "shots": [{
        "index": 1, "start_time": None,
        "description": ["A woman waits beneath the station canopy."],
        "camera": "A slow push-in follows her gaze.",
        "camera_motion": "push_in", "camera_amplitude": "small",
        "camera_speed": "slow", "camera_target": "the woman",
        "characters": [], "audio_notes": "Distant train wheels approach.",
        "dialogues": [], "references": [], "on_screen_text": [],
    }],
}


def _valid_prompt(soundscape: str = "Rain falls on the roof.") -> str:
    return (
        "integrated_multimodal_description: [Shot 1] A woman waits beneath "
        "the station canopy. Camera: slow push-in toward the woman. "
        "Synchronized audio: distant train wheels approach.\n"
        f"overall_soundscape: {soundscape}\n"
        "non_diegetic_music: N/A")


def test_h3_studio_public_interface_removes_operation_and_plan_port() -> None:
    inputs = studio_mod.APS_H3PromptStudio.INPUT_TYPES()
    assert inputs["required"]["execution_mode"][1]["default"] == "lenient"
    assert "operation" not in inputs["required"] | inputs["optional"]
    assert studio_mod.APS_H3PromptStudio.RETURN_NAMES == (
        "prompt", "prompt_session", "REFERENCE_MANIFEST", "validation",
        "change_summary")
    assert studio_mod.APS_H3PromptStudio.OUTPUT_NODE is True


def test_h3_lenient_create_and_refine_commit_freeform(monkeypatch, store) -> None:
    SequenceGateway.responses = [
        f"<PROMPT>{_valid_prompt()}</PROMPT><SUMMARY>Created.</SUMMARY>",
        f"<PROMPT>{_valid_prompt('Wind and rain move across the roof.')}</PROMPT>"
        "<SUMMARY>Changed the ambience.</SUMMARY>",
    ]
    SequenceGateway.requests = []
    monkeypatch.setattr(studio_mod, "Gateway", SequenceGateway)
    node = studio_mod.APS_H3PromptStudio()
    created = node.run(
        _profile(store), "woman waits for a train", "T2VA", 10.0,
        "lenient", message_nonce="h1")
    session = PromptSession.from_json(created["result"][1])
    assert session.current_payload_kind == "freeform" and session.revision == 1
    refined = node.run(
        store.get_profile("h3-studio").node_payload(),
        "make the ambience windier", "T2VA", 10.0, "lenient",
        prompt_session=created["result"][1], message_nonce="h2")
    session2 = PromptSession.from_json(refined["result"][1])
    assert session2.revision == 2
    assert "Wind and rain" in refined["result"][0]
    sent = SequenceGateway.requests[-1].messages[-1].content
    assert "current_prompt" in sent and "make the ambience windier" in sent


def test_h3_strict_create_and_refine_use_one_call_each(monkeypatch, store) -> None:
    SequenceGateway.responses = [
        json.dumps(PLAN),
        json.dumps({
            "base_revision": 1, "plan_type": "minimax_h3",
            "change_category": "minimal_refine", "intent_scope": ["soundscape"],
            "requested_changes": [{
                "path": "soundscape", "operation": "set",
                "value_json": json.dumps("Wind moves through the station."),
                "reason": "The user requested stronger wind ambience.",
            }],
            "dependent_changes": [], "invalidated_facts": [],
            "constraint_conflicts": [], "summary": "Changed the soundscape.",
        }),
    ]
    SequenceGateway.requests = []
    monkeypatch.setattr(studio_mod, "Gateway", SequenceGateway)
    node = studio_mod.APS_H3PromptStudio()
    created = node.run(
        _profile(store), "woman waits for a train", "T2VA", 10.0,
        "strict", message_nonce="s1")
    session = PromptSession.from_json(created["result"][1])
    assert session.current_payload_kind == "structured" and session.revision == 1
    refined = node.run(
        store.get_profile("h3-studio").node_payload(), "stronger wind ambience",
        "T2VA", 10.0, "strict", prompt_session=created["result"][1],
        message_nonce="s2")
    assert "Wind moves through" in refined["result"][0]
    assert PromptSession.from_json(refined["result"][1]).revision == 2
    assert len(SequenceGateway.requests) == 2


def test_h3_strict_protocol_repairs_once_then_fails_without_state(
        monkeypatch, store) -> None:
    SequenceGateway.responses = ["{broken", "still broken"]
    SequenceGateway.requests = []
    monkeypatch.setattr(studio_mod, "Gateway", SequenceGateway)
    with pytest.raises(ValueError, match="H3 严格结构化协议"):
        studio_mod.APS_H3PromptStudio().run(
            _profile(store), "woman waits", "T2VA", 10.0, "strict",
            message_nonce="bad")
    assert len(SequenceGateway.requests) == 2


def test_h3_strict_validator_failure_does_not_creatively_repair(
        monkeypatch, store) -> None:
    invalid = dict(PLAN)
    invalid["soundscape"] = ""
    SequenceGateway.responses = [json.dumps(invalid)]
    SequenceGateway.requests = []
    monkeypatch.setattr(studio_mod, "Gateway", SequenceGateway)
    with pytest.raises(ValueError, match="H3 严格模式校验未通过"):
        studio_mod.APS_H3PromptStudio().run(
            _profile(store), "silent-looking station", "T2VA", 10.0,
            "strict", message_nonce="invalid")
    assert len(SequenceGateway.requests) == 1


def test_h3_successful_mode_switch_starts_new_strict_lineage(
        monkeypatch, store) -> None:
    SequenceGateway.responses = [
        f"<PROMPT>{_valid_prompt()}</PROMPT><SUMMARY>Created.</SUMMARY>",
        json.dumps(PLAN),
    ]
    SequenceGateway.requests = []
    monkeypatch.setattr(studio_mod, "Gateway", SequenceGateway)
    node = studio_mod.APS_H3PromptStudio()
    lenient = node.run(_profile(store), "woman waits", "T2VA", 10.0,
                       "lenient", message_nonce="l1")
    old = PromptSession.from_json(lenient["result"][1])
    strict = node.run(
        store.get_profile("h3-studio").node_payload(), "rebuild strictly",
        "T2VA", 10.0, "strict", prompt_session=lenient["result"][1],
        message_nonce="s1")
    new = PromptSession.from_json(strict["result"][1])
    assert new.id != old.id
    assert new.execution_mode == "strict" and new.revision == 1


def test_h3_strict_i2va_requires_connected_image_before_commit(
        monkeypatch, store) -> None:
    SequenceGateway.responses = [json.dumps(PLAN)]
    SequenceGateway.requests = []
    monkeypatch.setattr(studio_mod, "Gateway", SequenceGateway)
    with pytest.raises(ValueError, match="I2VA.*1"):
        studio_mod.APS_H3PromptStudio().run(
            _profile(store), "animate the supplied first frame", "I2VA", 10.0,
            "strict", message_nonce="missing-image")
    assert len(SequenceGateway.requests) == 1


def test_h3_lenient_missing_connected_identity_repairs_once_then_rejects(
        monkeypatch, store) -> None:
    bible = CharacterBible(character_id="rin", name="Rin", traits=[
        CharacterTrait(name="hair", value="long black hair", category="stable",
                       locked=True)])
    SequenceGateway.responses = [
        f"<PROMPT>{_valid_prompt()}</PROMPT><SUMMARY>Created.</SUMMARY>",
        f"<PROMPT>{_valid_prompt()}</PROMPT><SUMMARY>Repaired.</SUMMARY>",
    ]
    SequenceGateway.requests = []
    monkeypatch.setattr(studio_mod, "Gateway", SequenceGateway)
    with pytest.raises(ValueError, match="身份锚点"):
        studio_mod.APS_H3PromptStudio().run(
            _profile(store), "Rin waits", "T2VA", 10.0, "lenient",
            character_bible=bible.to_json(), message_nonce="identity")
    assert len(SequenceGateway.requests) == 2

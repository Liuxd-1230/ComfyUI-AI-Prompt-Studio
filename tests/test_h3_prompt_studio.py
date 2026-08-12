"""H3 Prompt Studio behavior through its public Comfy node interface."""
from __future__ import annotations

import json

import pytest

import aps.nodes.h3_prompt_studio as studio_mod
from aps.domain.recovery_journal import DurableRecoveryJournal
from aps.schemas.character import CharacterBible, CharacterTrait
from aps.schemas.prompt_session import PromptSession
from aps.schemas.references import AssetRef, ReferenceManifest
from aps.schemas.results import LLMResult
from aps.services.h3_studio_runtime import normalize_plan


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


def test_h3_normalizer_removes_first_shot_zero_timestamp() -> None:
    payload = json.loads(json.dumps(PLAN))
    payload["shots"][0]["start_time"] = 0.0
    plan = studio_mod.parse_plan_json(json.dumps(payload), "T2VA", 8.0)

    normalized = normalize_plan(
        plan, ReferenceManifest(), image_count=0, mode="T2VA", duration=8.0)

    assert normalized.shots[0].start_time is None


def test_h3_studio_public_interface_removes_operation_and_plan_port() -> None:
    inputs = studio_mod.APS_H3PromptStudio.INPUT_TYPES()
    assert inputs["required"]["execution_mode"][1]["default"] == "lenient"
    assert "operation" not in inputs["required"] | inputs["optional"]
    assert studio_mod.APS_H3PromptStudio.RETURN_NAMES == (
        "prompt", "prompt_session", "REFERENCE_MANIFEST", "validation",
        "change_summary")
    assert studio_mod.APS_H3PromptStudio.OUTPUT_NODE is True
    assert inputs["required"]["mode"][0] == [
        "T2VA", "I2VA", "FL2VA", "L2VA", "Ref2VA"]
    assert "R2V" not in inputs["required"]["mode"][0]
    assert inputs["hidden"]["unique_id"] == "UNIQUE_ID"


def test_h3_public_node_persists_recoverable_session(
        monkeypatch, store, tmp_path) -> None:
    journal_path = tmp_path / "recovery-journal.json"
    journal = DurableRecoveryJournal(journal_path)
    monkeypatch.setattr(studio_mod, "get_recovery_journal", lambda: journal)
    SequenceGateway.responses = [
        f"<PROMPT>{_valid_prompt()}</PROMPT><SUMMARY>Created.</SUMMARY>"]
    SequenceGateway.requests = []
    monkeypatch.setattr(studio_mod, "Gateway", SequenceGateway)

    result = studio_mod.APS_H3PromptStudio().run(
        _profile(store), "woman waits for a train", "T2VA", 10.0,
        "lenient", message_nonce="h-journal", unique_id="h3-8")
    session = PromptSession.from_json(result["result"][1])
    restored = DurableRecoveryJournal(journal_path).latest(session.id, "h3-8")

    assert session.node_instance_id == "h3-8"
    assert restored is not None
    assert restored.session_snapshot["current_prompt"] == result["result"][0]


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


def test_h3_lenient_repairs_pan_when_user_requested_truck(monkeypatch, store) -> None:
    wrong = (_valid_prompt().replace("push-in", "pan right")
             .replace("\noverall_soundscape:",
                      " [Shot 2] At 00:05.000 A needless cut.\noverall_soundscape:"))
    corrected = _valid_prompt().replace("push-in", "truck right")
    SequenceGateway.responses = [
        f"<PROMPT>{wrong}</PROMPT><SUMMARY>Moved right.</SUMMARY>",
        f"<PROMPT>{corrected}</PROMPT><SUMMARY>Corrected terminology.</SUMMARY>",
    ]
    SequenceGateway.requests = []
    monkeypatch.setattr(studio_mod, "Gateway", SequenceGateway)

    result = studio_mod.APS_H3PromptStudio().run(
        _profile(store), "单镜头缓慢向右横移", "T2VA", 10.0,
        "lenient", message_nonce="truck")
    session = PromptSession.from_json(result["result"][1])

    assert "truck right" in result["result"][0]
    assert "[Shot 2]" not in result["result"][0]
    assert session.revisions[-1].repair_count == 1
    assert len(SequenceGateway.requests) == 2
    assert "Never translate 横移 as pan" in SequenceGateway.requests[0].system
    assert "一镜到底/单镜头" in SequenceGateway.requests[0].system


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


def test_h3_strict_delete_middle_shot_reindexes_public_output(monkeypatch, store) -> None:
    payload = json.loads(json.dumps(PLAN))
    payload["shots"] = [
        {"index": 1, "start_time": None,
         "description": ["First shot."], "camera": "Static wide shot."},
        {"index": 2, "start_time": 3.0,
         "description": ["Middle shot to remove."], "camera": "Medium shot."},
        {"index": 3, "start_time": 6.0,
         "description": ["Last shot remains."], "camera": "Close-up."},
    ]
    changeset = {
        "base_revision": 1, "plan_type": "minimax_h3",
        "change_category": "minimal_refine", "intent_scope": ["shots/1"],
        "requested_changes": [{
            "path": "shots/1", "operation": "delete", "value_json": "null",
            "reason": "The user explicitly removed the middle shot.",
        }],
        "dependent_changes": [], "invalidated_facts": [],
        "constraint_conflicts": [], "summary": "Removed the middle shot.",
    }
    SequenceGateway.responses = [json.dumps(payload), json.dumps(changeset)]
    SequenceGateway.requests = []
    monkeypatch.setattr(studio_mod, "Gateway", SequenceGateway)
    node = studio_mod.APS_H3PromptStudio()
    created = node.run(
        _profile(store), "create three shots", "T2VA", 10.0,
        "strict", message_nonce="delete-create")
    refined = node.run(
        store.get_profile("h3-studio").node_payload(), "remove the middle shot",
        "T2VA", 10.0, "strict", prompt_session=created["result"][1],
        message_nonce="delete-middle")
    session = PromptSession.from_json(refined["result"][1])
    plan_after = session.current_plan["h3_plan"]
    assert [shot["index"] for shot in plan_after["shots"]] == [1, 2]
    assert [shot["description"][0] for shot in plan_after["shots"]] == [
        "First shot.", "Last shot remains."]
    assert "[Shot 1]" in refined["result"][0]
    assert "[Shot 2]" in refined["result"][0]
    assert "[Shot 3]" not in refined["result"][0]


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


def test_h3_lenient_failure_exposes_bounded_raw_and_exact_format_contract(
        monkeypatch, store) -> None:
    SequenceGateway.responses = ["first malformed H3 text", "second malformed H3 text"]
    SequenceGateway.requests = []
    monkeypatch.setattr(studio_mod, "Gateway", SequenceGateway)
    with pytest.raises(ValueError, match="second malformed H3 text"):
        studio_mod.APS_H3PromptStudio().run(
            _profile(store), "woman waits", "T2VA", 10.0, "lenient",
            message_nonce="bad-lenient")
    assert len(SequenceGateway.requests) == 2
    for request in SequenceGateway.requests:
        assert "integrated_multimodal_description:" in request.system
        assert "overall_soundscape:" in request.system
        assert "non_diegetic_music:" in request.system
        assert "Never generalize or substitute a concrete location" in request.system
        assert "Distinguish zoom from push, pan from truck" in request.system


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


def test_h3_display_name_is_not_a_required_visual_anchor() -> None:
    """A UI/library label is not itself a drawable identity fact."""
    bible = CharacterBible(character_id="rose", name="玫瑰午睡时", traits=[
        CharacterTrait(name="hair", value="long dark wavy hair", category="stable")])
    parsed = studio_mod.LenientPromptOutput(
        prompt=_valid_prompt(), summary="", kind="tagged")

    report = studio_mod._validate_lenient_h3(
        parsed, "T2VA", 5.0, ReferenceManifest(), 0, [bible], "woman waits")

    assert report.valid
    assert not any(issue.code == "h3_identity_anchor_missing"
                   for issue in report.issues)


def test_h3_rejects_near_copy_display_name_drift() -> None:
    bible = CharacterBible(character_id="rose", name="玫瑰午睡时")
    parsed = studio_mod.LenientPromptOutput(
        prompt=_valid_prompt().replace("A woman", "玫瑰午时睡"),
        summary="", kind="tagged")

    report = studio_mod._validate_lenient_h3(
        parsed, "T2VA", 5.0, ReferenceManifest(), 0, [bible], "woman waits")

    assert not report.valid
    assert any(issue.code == "h3_identity_name_drift" for issue in report.issues)


def test_h3_i2va_alignment_consumes_picture_without_ref2va_retention() -> None:
    """Base-mode alignment is the reference contract; retention belongs to Ref2VA."""
    plan = studio_mod.parse_plan_json(json.dumps(PLAN), "I2VA", 5.0)
    manifest = ReferenceManifest(assets=[
        AssetRef(asset_id="img_0", asset_type="image", data_ref="image_tensor")])

    normalized = normalize_plan(
        plan, manifest, image_count=1, mode="I2VA", duration=5.0)
    rendered, report = studio_mod.render_validate(
        normalized, manifest, image_count=1, mode="I2VA", duration=5.0)

    assert rendered.startswith(
        "For the target video, at 0.00 seconds into the target video, "
        "<Picture 1> (from [Shot 1]) is fully referenced.")
    assert report.valid
    assert not any(issue.code in {
        "h3_reference_unused", "h3_reference_retention_missing"}
        for issue in report.issues)

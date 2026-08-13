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
from aps.services.h3_plan import parse_plan_json
from aps.services.h3_studio_runtime import normalize_plan, render_validate


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
    plan = parse_plan_json(json.dumps(payload), "T2VA", 8.0)

    normalized = normalize_plan(
        plan, ReferenceManifest(), image_count=0, mode="T2VA", duration=8.0)

    assert normalized.shots[0].start_time is None


def test_h3_studio_public_interface_removes_operation_and_plan_port() -> None:
    inputs = studio_mod.APS_H3PromptStudio.INPUT_TYPES()
    assert "execution_mode" not in inputs["required"] | inputs["optional"]
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
        _profile(store), "woman waits for a train", "T2VA", 10.0, message_nonce="h-journal", unique_id="h3-8")
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
        _profile(store), "woman waits for a train", "T2VA", 10.0, message_nonce="h1")
    session = PromptSession.from_json(created["result"][1])
    assert session.current_payload_kind == "freeform" and session.revision == 1
    refined = node.run(
        store.get_profile("h3-studio").node_payload(),
        "make the ambience windier", "T2VA", 10.0,
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
        _profile(store), "单镜头缓慢向右横移", "T2VA", 10.0, message_nonce="truck")
    session = PromptSession.from_json(result["result"][1])

    assert "truck right" in result["result"][0]
    assert "[Shot 2]" not in result["result"][0]
    assert session.revisions[-1].repair_count == 1
    assert len(SequenceGateway.requests) == 2
    assert "Never translate 横移 as pan" in SequenceGateway.requests[0].system
    assert "一镜到底/单镜头" in SequenceGateway.requests[0].system


def test_h3_format_repair_caps_high_reasoning_at_medium(monkeypatch, store) -> None:
    SequenceGateway.responses = [
        "malformed first response",
        f"<PROMPT>{_valid_prompt()}</PROMPT><SUMMARY>Repaired.</SUMMARY>",
    ]
    SequenceGateway.requests = []
    monkeypatch.setattr(studio_mod, "Gateway", SequenceGateway)
    profile = _profile(store)
    profile["reasoning"] = "high"

    studio_mod.APS_H3PromptStudio().run(
        profile, "woman waits", "T2VA", 8.0, message_nonce="repair-reasoning")

    assert SequenceGateway.requests[1].reasoning == "medium"


def test_h3_lenient_failure_exposes_bounded_raw_and_exact_format_contract(
        monkeypatch, store) -> None:
    SequenceGateway.responses = ["first malformed H3 text", "second malformed H3 text"]
    SequenceGateway.requests = []
    monkeypatch.setattr(studio_mod, "Gateway", SequenceGateway)
    with pytest.raises(ValueError, match="second malformed H3 text"):
        studio_mod.APS_H3PromptStudio().run(
            _profile(store), "woman waits", "T2VA", 10.0,
            message_nonce="bad-lenient")
    assert len(SequenceGateway.requests) == 2
    for request in SequenceGateway.requests:
        assert "integrated_multimodal_description:" in request.system
        assert "overall_soundscape:" in request.system
        assert "non_diegetic_music:" in request.system
        assert "Never generalize or substitute a concrete location" in request.system
        assert "Distinguish zoom from push, pan from truck" in request.system


@pytest.mark.parametrize("mode, required", [
    ("I2VA", (
        "Copy this exact skeleton",
        "integrated_multimodal_description: [Shot 1]",
        "The alignment line is not a shot",
        "Do not write a timestamp after [Shot 1]",
    )),
    ("FL2VA", (
        "Copy this exact skeleton",
        "How the reference pictures align with the target video —",
        "integrated_multimodal_description: [Shot 1]",
        "Do not switch to the six-section Ref2VA format",
    )),
    ("Ref2VA", (
        "summary: [reference generation]",
        "<Picture 1>: fully_preserved",
        "Do not define visual contents that are absent from task data",
    )),
])
def test_h3_public_request_contains_small_model_mode_skeleton(
        monkeypatch, store, mode, required) -> None:
    SequenceGateway.responses = [
        f"<PROMPT>{_valid_prompt()}</PROMPT><SUMMARY>Created.</SUMMARY>",
        f"<PROMPT>{_valid_prompt()}</PROMPT><SUMMARY>Repaired.</SUMMARY>",
    ]
    SequenceGateway.requests = []
    monkeypatch.setattr(studio_mod, "Gateway", SequenceGateway)

    try:
        studio_mod.APS_H3PromptStudio().run(
            _profile(store), "one woman dances in a livestream", mode, 8.0,
            message_nonce=f"skeleton-{mode}")
    except ValueError:
        # The fixture prompt is intentionally T2VA-shaped. This test observes the
        # public node's real assembled request, not validation of that fixture.
        pass

    system = SequenceGateway.requests[0].system
    for marker in required:
        assert marker in system
    assert "cannot inspect raw connected media pixels" in system


def test_h3_protocol_normalizer_recovers_i2va_prose_after_alignment() -> None:
    raw = (
        "For the target video, at 0.00 seconds into the target video, "
        "<Picture 1> (from [Shot 2]) is fully referenced. The handheld camera "
        "frames a woman dancing while pedestrians glance at her.\n"
        "overall_soundscape: footsteps and traffic\n"
        "non_diegetic_music: N/A")

    normalized = studio_mod._normalize_lenient_h3_protocol(raw, "I2VA")

    assert normalized.startswith(
        "For the target video, at 0.00 seconds into the target video, "
        "<Picture 1> (from [Shot 1]) is fully referenced.\n")
    assert "integrated_multimodal_description: [Shot 1] The handheld camera" in normalized
    assert "[Shot 2]" not in normalized


def test_h3_protocol_normalizer_removes_compact_zero_timestamp_from_shot_one() -> None:
    raw = (
        "How the reference pictures align with the target video — Picture 1 at "
        "0.00 seconds and Picture 2 at 8.00 seconds.\n"
        "integrated_multimodal_description: [Shot 1] At 0.00s; A handheld view.\n"
        "overall_soundscape: traffic\nnon_diegetic_music: N/A")

    normalized = studio_mod._normalize_lenient_h3_protocol(raw, "FL2VA")

    assert "[Shot 1] A handheld view." in normalized
    assert "[Shot 1] At 0.00s" not in normalized


def test_h3_protocol_normalizer_reindexes_body_and_normalizes_second_timestamps() -> None:
    raw = (
        "For the target video, at 0.00 seconds into the target video, "
        "<Picture 1> (from [Shot 1]) is fully referenced.\n"
        "integrated_multimodal_description: [Shot 2] At 0.04 seconds into the "
        "target video, the woman begins dancing. [Shot 3] At 4.2s; pedestrians "
        "glance and continue walking.\n"
        "overall_soundscape: traffic\nnon_diegetic_music: N/A")

    normalized = studio_mod._normalize_lenient_h3_protocol(raw, "I2VA")

    assert "integrated_multimodal_description: [Shot 1] the woman begins dancing." in normalized
    assert "[Shot 2] At 00:04.200 pedestrians" in normalized
    assert "[Shot 3]" not in normalized


def test_h3_protocol_normalizer_removes_repeated_i2va_alignment_from_body() -> None:
    raw = (
        "For the target video, at 0.00 seconds into the target video, "
        "<Picture 1> (from [Shot 1]) is fully referenced.\n"
        "integrated_multimodal_description: [Shot 2] At 0.04 seconds into the "
        "target video, <Picture 1> (from [Shot 1]) is fully referenced. "
        "A handheld camera frames the dancer.\n"
        "overall_soundscape: traffic\nnon_diegetic_music: N/A")

    normalized = studio_mod._normalize_lenient_h3_protocol(raw, "I2VA")

    assert normalized.count("fully referenced") == 1
    assert "integrated_multimodal_description: [Shot 1] A handheld camera" in normalized
    assert "[Shot 0]" not in normalized


def test_h3_protocol_normalizer_converts_decimal_second_phrases_in_body() -> None:
    raw = (
        "How the reference pictures align with the target video — Picture 1 at "
        "0.00 seconds and Picture 2 at 8.00 seconds.\n"
        "integrated_multimodal_description: [Shot 1] At 0.000s, she starts. "
        "At 8.000s, she finishes.\n"
        "overall_soundscape: traffic\nnon_diegetic_music: N/A")

    normalized = studio_mod._normalize_lenient_h3_protocol(raw, "FL2VA")

    assert "[Shot 1] she starts." in normalized
    assert "At 00:08.000, she finishes." in normalized


def test_h3_protocol_normalizer_removes_bare_template_placeholder() -> None:
    raw = _valid_prompt().replace(
        "A woman waits", "A woman dances as <PARTICLE> dust crosses the frame")

    normalized = studio_mod._normalize_lenient_h3_protocol(raw, "T2VA")

    assert "<PARTICLE>" not in normalized
    assert "dust crosses the frame" in normalized


def test_h3_public_validation_rejects_hundredth_second_duration_confusion() -> None:
    parsed = studio_mod.LenientPromptOutput(
        prompt=_valid_prompt().replace(
            "A woman waits", "A woman dances and ends at 0.08 seconds"),
        summary="", kind="tagged")

    report = studio_mod._validate_lenient_h3(
        parsed, "T2VA", 8.0, ReferenceManifest(), 0, [], "a woman dances")

    assert not report.valid
    assert any(issue.code == "h3_decimal_second_confusion"
               for issue in report.issues)


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
            _profile(store), "Rin waits", "T2VA", 10.0,
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


def test_h3_identity_anchor_accepts_natural_article_insertion() -> None:
    bible = CharacterBible(character_id="rose", name="Rose", traits=[
        CharacterTrait(name="dress",
                       value="ivory Victorian rose dress with black floral sash",
                       category="stable", locked=True)])
    parsed = studio_mod.LenientPromptOutput(
        prompt=_valid_prompt().replace(
            "A woman", "Rose wears an ivory Victorian rose dress with a black floral sash"),
        summary="", kind="tagged")

    report = studio_mod._validate_lenient_h3(
        parsed, "T2VA", 5.0, ReferenceManifest(), 0, [bible], "Rose waits")

    assert not any(issue.code == "h3_identity_anchor_missing"
                   for issue in report.issues)


def test_h3_strict_normalization_injects_locked_bible_traits() -> None:
    bible = CharacterBible(character_id="rose", name="Rose", speaker_id="S1", traits=[
        CharacterTrait(name="hair", value="long wavy black hair",
                       category="stable", locked=True),
        CharacterTrait(name="eyes", value="amber-green eyes",
                       category="stable", locked=True)])
    plan = parse_plan_json(json.dumps(PLAN), "T2VA", 5.0)

    normalized = normalize_plan(
        plan, ReferenceManifest(), image_count=0, mode="T2VA", duration=5.0,
        source_bibles=[bible])
    rendered, _ = render_validate(
        normalized, ReferenceManifest(), image_count=0, mode="T2VA", duration=5.0)

    assert "Rose's locked visual identity: long wavy black hair, amber-green eyes." in rendered


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
    plan = parse_plan_json(json.dumps(PLAN), "I2VA", 5.0)
    manifest = ReferenceManifest(assets=[
        AssetRef(asset_id="img_0", asset_type="image", data_ref="image_tensor")])

    normalized = normalize_plan(
        plan, manifest, image_count=1, mode="I2VA", duration=5.0)
    rendered, report = render_validate(
        normalized, manifest, image_count=1, mode="I2VA", duration=5.0)

    assert rendered.startswith(
        "For the target video, at 0.00 seconds into the target video, "
        "<Picture 1> (from [Shot 1]) is fully referenced.")
    assert report.valid
    assert not any(issue.code in {
        "h3_reference_unused", "h3_reference_retention_missing"}
        for issue in report.issues)


def test_h3_connected_images_reuse_analyzer_manifest_assets() -> None:
    from aps.services.h3_studio_runtime import prepare_manifest

    manifest = ReferenceManifest(assets=[
        AssetRef(asset_id="img_0", asset_type="image", data_ref="image_tensor")])
    class TwoImages:
        shape = (2, 8, 8, 3)

    prepared, count = prepare_manifest(
        manifest.to_json(), TwoImages(), (None, None, None), (None, None, None))

    assert count == 2
    assert len([asset for asset in prepared.assets
                if asset.asset_type == "image"]) == 2
    assert [asset.h3_labels[0] for asset in prepared.assets] == [
        "Picture 1", "Picture 2"]


def test_h3_manifest_asset_ids_are_canonicalized_without_duplicates() -> None:
    from aps.schemas.h3 import H3Asset, H3PromptPlan, H3Retention, H3Shot, H3Subject
    from aps.services.h3_plan import sync_manifest_assets

    manifest = ReferenceManifest(assets=[AssetRef(
        asset_id="img_0", asset_type="image", data_ref="image_tensor",
        h3_labels=["Picture 1"])])
    plan = H3PromptPlan(
        mode="Ref2VA",
        assets=[H3Asset(label="img_0", kind="picture"),
                H3Asset(label="Picture 1", kind="picture")],
        subjects=[H3Subject(label="Subject 1", source_assets=["img_0"])],
        retention=[H3Retention(label="img_0")],
        shots=[H3Shot(references=["img_0"])],
    )

    sync_manifest_assets(plan, manifest)

    assert [asset.label for asset in plan.assets] == ["Picture 1"]
    assert plan.subjects[0].source_assets == ["Picture 1"]
    assert plan.retention[0].label == "Picture 1"
    assert plan.shots[0].references == ["Picture 1", "Subject 1"]


def test_h3_locked_manifest_subject_gets_deterministic_retention() -> None:
    from aps.schemas.h3 import H3PromptPlan, H3Shot
    from aps.schemas.references import SubjectRef
    from aps.services.h3_plan import sync_manifest_assets

    manifest = ReferenceManifest(
        assets=[AssetRef(asset_id="img_0", asset_type="image",
                         h3_labels=["Picture 1"])],
        subjects=[SubjectRef(subject_id="rose", kind="character",
                             definition="Rose", source_assets=["img_0"],
                             locked=True)])
    plan = H3PromptPlan(mode="Ref2VA", shots=[
        H3Shot(index=1, references=["Picture 1"])])

    sync_manifest_assets(plan, manifest)

    subject_retention = next(item for item in plan.retention
                             if item.label == "Subject 1")
    assert subject_retention.marker == "fully_preserved"
    assert subject_retention.shot_refs == ["Shot 1"]


def test_lenient_h3_normalizes_bracketed_official_headings() -> None:
    raw = (
        "[integrated_multimodal_description][Shot 1] A woman lifts a rose.\n"
        "[overall_soundscape]Room tone and cloth rustle.\n"
        "[non_diegetic_music]N/A"
    )

    normalized = studio_mod._normalize_lenient_h3_protocol(raw, "T2VA")

    assert normalized.startswith(
        "integrated_multimodal_description: [Shot 1] A woman lifts a rose.")
    assert "overall_soundscape: Room tone" in normalized
    assert "non_diegetic_music: N/A" in normalized


def test_lenient_h3_normalizes_tagged_headings_and_shot_one_zero_time() -> None:
    raw = (
        "<integrated_multimodal_description>\n"
        "[Shot 1] At 00:00.000; A woman lifts a rose.\n"
        "</integrated_multimodal_description>\n"
        "<overall_soundscape>Room tone.</overall_soundscape>\n"
        "<non_diegetic_music>N/A</non_diegetic_music>"
    )

    normalized = studio_mod._normalize_lenient_h3_protocol(raw, "T2VA")

    assert "integrated_multimodal_description: [Shot 1] A woman" in normalized
    assert "overall_soundscape: Room tone." in normalized
    assert "non_diegetic_music: N/A" in normalized
    assert "</" not in normalized


def test_lenient_h3_moves_base_field_before_a_stray_first_shot() -> None:
    raw = (
        "How the reference pictures align with the target video — final frame.\n"
        "[Shot 1] A woman lifts a rose.\n"
        "integrated_multimodal_description: A continuous shot.\n"
        "overall_soundscape: Room tone.\n"
        "non_diegetic_music: N/A"
    )

    normalized = studio_mod._normalize_lenient_h3_protocol(raw, "L2VA")

    assert "integrated_multimodal_description: [Shot 1] A woman lifts a rose." in normalized
    assert normalized.count("integrated_multimodal_description:") == 1


def test_lenient_h3_pads_single_digit_timestamp_minute() -> None:
    raw = (
        "subject_definitions:\n<Picture 1> woman\n"
        "summary:\n[reference generation] shot\nretention_analysis:\n"
        "<Picture 1>: fully_preserved\n"
        "detailed_description:\n[Shot 1] At 0:00.000, woman lifts a rose.\n"
        "overall_soundscape:\nRoom tone.\nnon_diegetic_music:\nN/A"
    )

    normalized = studio_mod._normalize_lenient_h3_protocol(raw, "Ref2VA")

    assert "[Shot 1] woman lifts a rose." in normalized
    assert "0:00.000" not in normalized


def test_lenient_h3_recovers_missing_opening_field_tag() -> None:
    raw = (
        "[Shot 1] At 00:00.000; A woman lifts a rose.\n"
        "</integrated_multimodal_description>\n"
        "<overall_soundscape>Room tone.</overall_soundscape>\n"
        "<non_diegetic_music>N/A</non_diegetic_music>"
    )

    normalized = studio_mod._normalize_lenient_h3_protocol(raw, "T2VA")

    assert normalized.startswith(
        "integrated_multimodal_description: [Shot 1] A woman lifts a rose.")
    assert "</integrated" not in normalized

"""Image Prompt Studio behavior through the public Comfy node interface."""
from __future__ import annotations

import json

import pytest

import aps.nodes.prompt_studio as studio_mod
from aps.domain.recovery_journal import DurableRecoveryJournal
from aps.schemas.character import CharacterBible, CharacterTrait
from aps.schemas.prompt_session import PromptSession
from aps.schemas.prompt_plan import ValidationReport
from aps.schemas.references import ReferenceManifest
from aps.schemas.results import LLMResult
from aps.schemas.storyboard import StoryItem
from aps.services.prompt_protocol import LenientPromptOutput


def _profile(store):
    store.create_profile({"profile_id": "studio", "name": "Local Studio"})
    store.set_api_key("studio", "lm-studio-local")
    return store.get_profile("studio").node_payload()


class SequenceGateway:
    responses: list[str] = []
    requests: list[object] = []

    def generate(self, profile, api_key, request):
        del profile, api_key
        type(self).requests.append(request)
        return LLMResult(text=type(self).responses.pop(0))


def test_prompt_studio_public_interface_has_no_operation_or_plan_ports() -> None:
    inputs = studio_mod.APS_PromptStudio.INPUT_TYPES()
    assert inputs["required"]["execution_mode"][1]["default"] == "lenient"
    assert "operation" not in inputs["required"] | inputs.get("optional", {})
    assert studio_mod.APS_PromptStudio.RETURN_NAMES == (
        "positive", "negative", "prompt_session", "validation",
        "change_summary")
    assert studio_mod.APS_PromptStudio.OUTPUT_NODE is True


def test_prompt_studio_consumes_public_story_item_schema() -> None:
    item = StoryItem(
        item_id="shot_1", kind="shot", title="Rainy carriage",
        text="Rin reads a letter beside a rain-covered train window.",
        location="train carriage", camera="medium shot")

    combined = studio_mod._input_text("Use cool fluorescent light.", item.to_json())

    assert "Rin reads a letter" in combined
    assert "medium shot" in combined
    assert "Use cool fluorescent light" in combined


def test_lenient_create_and_refine_commit_freeform_revisions(
        monkeypatch, store) -> None:
    SequenceGateway.responses = [
        "<PROMPT>A woman walks through blue-hour rain.</PROMPT>"
        "<SUMMARY>Created the scene.</SUMMARY>",
        "<PROMPT>A woman in a red coat walks through warm evening rain.</PROMPT>"
        "<SUMMARY>Changed the coat and lighting.</SUMMARY>",
    ]
    SequenceGateway.requests = []
    monkeypatch.setattr(studio_mod, "Gateway", SequenceGateway)
    node = studio_mod.APS_PromptStudio()
    created = node.run(
        AI_PROFILE=_profile(store), text="A woman walking in rain",
        target="anima_base", execution_mode="lenient")
    positive, negative, session_json, validation, summary = created
    session = PromptSession.from_json(session_json)
    assert positive == "A woman walks through blue-hour rain."
    assert negative
    assert session.execution_mode == "lenient"
    assert session.current_payload_kind == "freeform"
    assert session.revision == 1
    assert "通过" in validation and summary == "Created the scene."

    refined = node.run(
        AI_PROFILE=store.get_profile("studio").node_payload(),
        text="Change her coat to red and make the light warm.",
        target="anima_base", execution_mode="lenient",
        prompt_session=session_json, message_nonce="refine-2")
    positive2, _, session_json2, _, summary2 = refined
    session2 = PromptSession.from_json(session_json2)
    assert positive2.startswith("A woman in a red coat")
    assert session2.revision == 2
    assert summary2 == "Changed the coat and lighting."
    sent = SequenceGateway.requests[-1].messages[-1].content
    assert "A woman walks through blue-hour rain." in sent
    assert "Change her coat to red" in sent
    assert "Created the scene" not in sent


def test_public_node_persists_journal_and_forks_copied_session(
        monkeypatch, store, tmp_path) -> None:
    journal_path = tmp_path / "recovery-journal.json"
    journal = DurableRecoveryJournal(journal_path)
    monkeypatch.setattr(studio_mod, "get_recovery_journal", lambda: journal)
    SequenceGateway.responses = [
        "<PROMPT>A woman in rain.</PROMPT><SUMMARY>Created.</SUMMARY>",
        "<PROMPT>A woman in warm rain.</PROMPT><SUMMARY>Refined copy.</SUMMARY>",
    ]
    SequenceGateway.requests = []
    monkeypatch.setattr(studio_mod, "Gateway", SequenceGateway)
    node = studio_mod.APS_PromptStudio()
    original = node.run(
        _profile(store), "woman in rain", "anima_base", "lenient",
        message_nonce="m1", unique_id="42")
    original_session = PromptSession.from_json(original["result"][2])

    copied = node.run(
        store.get_profile("studio").node_payload(), "make it warmer",
        "anima_base", "lenient", prompt_session=original["result"][2],
        message_nonce="m2", unique_id="99")
    copied_session = PromptSession.from_json(copied["result"][2])

    assert original_session.node_instance_id == "42"
    assert copied_session.node_instance_id == "99"
    assert copied_session.id != original_session.id
    assert copied_session.origin_session_id == original_session.id
    assert DurableRecoveryJournal(journal_path).latest(
        original_session.id, "42").result_revision == 1
    assert DurableRecoveryJournal(journal_path).latest(
        copied_session.id, "99").result_revision == 2


def test_lenient_untagged_prompt_commits_with_warning(monkeypatch, store) -> None:
    SequenceGateway.responses = [
        "A detailed English visual prompt showing Alice beside a quiet river."]
    SequenceGateway.requests = []
    monkeypatch.setattr(studio_mod, "Gateway", SequenceGateway)
    result = studio_mod.APS_PromptStudio().run(
        AI_PROFILE=_profile(store), text="Alice by a river",
        target="anima_base", execution_mode="lenient")
    assert result["result"][0].startswith("A detailed English")
    assert "未遵循标签协议" in result["result"][3]


def test_lenient_target_change_warns_and_updates_session_target(
        monkeypatch, store) -> None:
    SequenceGateway.responses = [
        "<PROMPT>A detailed river portrait in English.</PROMPT><SUMMARY>One.</SUMMARY>",
        "<PROMPT>Replace the background while preserving the subject.</PROMPT>"
        "<SUMMARY>Adapted for editing.</SUMMARY>",
    ]
    SequenceGateway.requests = []
    monkeypatch.setattr(studio_mod, "Gateway", SequenceGateway)
    node = studio_mod.APS_PromptStudio()
    created = node.run(
        AI_PROFILE=_profile(store), text="portrait", target="anima_base",
        execution_mode="lenient", message_nonce="target-1")
    changed = node.run(
        AI_PROFILE=store.get_profile("studio").node_payload(),
        text="turn this into an edit instruction", target="qwen_image_edit_2511",
        execution_mode="lenient", prompt_session=created["result"][2],
        message_nonce="target-2")
    session = PromptSession.from_json(changed["result"][2])
    assert (session.target_family, session.target_variant) == (
        "qwen_image_edit", "2511")
    assert "target_signature" in changed["result"][3]
    assert "target_signature" in changed["ui"]["validation"][0]


def test_lenient_protocol_garbage_repairs_once_without_committing_first_result(
        monkeypatch, store) -> None:
    SequenceGateway.responses = [
        '{"prompt":"broken", "summary":',
        "<PROMPT>A complete English prompt after format repair.</PROMPT>"
        "<SUMMARY>Reformatted only.</SUMMARY>",
    ]
    SequenceGateway.requests = []
    monkeypatch.setattr(studio_mod, "Gateway", SequenceGateway)
    result = studio_mod.APS_PromptStudio().run(
        AI_PROFILE=_profile(store), text="simple scene",
        target="anima_base", execution_mode="lenient")
    session = PromptSession.from_json(result["result"][2])
    assert result["result"][0] == "A complete English prompt after format repair."
    assert session.revision == 1
    assert session.revisions[-1].repair_count == 1
    assert len(SequenceGateway.requests) == 2


def test_lenient_anima_rejects_non_english_visual_prose(monkeypatch, store) -> None:
    SequenceGateway.responses = [
        "<PROMPT>一个女孩穿着红色外套走在雨中。</PROMPT><SUMMARY>创建</SUMMARY>",
        "<PROMPT>一个女孩穿着红色外套走在雨中。</PROMPT><SUMMARY>格式修复</SUMMARY>",
    ]
    SequenceGateway.requests = []
    monkeypatch.setattr(studio_mod, "Gateway", SequenceGateway)
    with pytest.raises(ValueError, match="ANIMA.*英语"):
        studio_mod.APS_PromptStudio().run(
            AI_PROFILE=_profile(store), text="女孩在雨中",
            target="anima_base", execution_mode="lenient")


def test_strict_create_and_refine_use_structured_plan_and_one_call_each(
        monkeypatch, store) -> None:
    SequenceGateway.responses = [
        json.dumps({
            "content": {
                "scene_description": "Alice walks through evening rain",
                "characters": [{
                    "character_id": "alice", "name": "Alice",
                    "required_traits": ["red coat"], "action": "walking",
                }],
                "environment": ["rainy street"],
                "lighting": "warm shop light",
            },
            "negative": "watermark",
        }),
        json.dumps({
            "base_revision": 1,
            "plan_type": "anima",
            "change_category": "minimal_refine",
            "intent_scope": ["content/lighting"],
            "requested_changes": [{
                "path": "content/lighting", "operation": "set",
                "value_json": json.dumps("cool moonlight"),
                "reason": "The user requested cooler light.",
            }],
            "dependent_changes": [], "invalidated_facts": [],
            "constraint_conflicts": [], "summary": "Changed the lighting.",
        }),
    ]
    SequenceGateway.requests = []
    monkeypatch.setattr(studio_mod, "Gateway", SequenceGateway)
    node = studio_mod.APS_PromptStudio()
    created = node.run(
        AI_PROFILE=_profile(store), text="Alice in a red coat in rainy street",
        target="anima_base", execution_mode="strict", message_nonce="s1")
    session = PromptSession.from_json(created["result"][2])
    assert session.execution_mode == "strict"
    assert session.current_payload_kind == "structured"
    assert session.revision == 1
    assert "Alice" in created["result"][0]

    refined = node.run(
        AI_PROFILE=store.get_profile("studio").node_payload(),
        text="Change the lighting to cool moonlight.", target="anima_base",
        execution_mode="strict", prompt_session=created["result"][2],
        message_nonce="s2")
    restored = PromptSession.from_json(refined["result"][2])
    assert restored.revision == 2
    assert "cool moonlight" in refined["result"][0]
    assert refined["result"][4] == "Changed the lighting."
    assert len(SequenceGateway.requests) == 2
    create_system = SequenceGateway.requests[0].system
    assert "Residual prose and notes must not repeat structured facts" in create_system
    assert "[OPERATION:operation.create@1.0]" in create_system
    properties = SequenceGateway.requests[0].output_contract.native_schema()["properties"]["content"]["properties"]
    assert "Usually return an empty string" in properties["scene_description"]["description"]
    assert "Return []" in properties["control_tags"]["description"]


def test_strict_protocol_failure_repairs_format_once_without_commit(
        monkeypatch, store) -> None:
    SequenceGateway.responses = ["{broken", "still not json"]
    SequenceGateway.requests = []
    monkeypatch.setattr(studio_mod, "Gateway", SequenceGateway)
    with pytest.raises(ValueError, match="still not json"):
        studio_mod.APS_PromptStudio().run(
            AI_PROFILE=_profile(store), text="Alice by a river",
            target="anima_base", execution_mode="strict", message_nonce="bad")
    assert len(SequenceGateway.requests) == 2


def test_failed_mode_switch_keeps_previous_serialized_lineage(
        monkeypatch, store) -> None:
    SequenceGateway.responses = [
        "<PROMPT>A complete English image prompt.</PROMPT><SUMMARY>Done.</SUMMARY>",
        "{broken", "still broken",
    ]
    SequenceGateway.requests = []
    monkeypatch.setattr(studio_mod, "Gateway", SequenceGateway)
    node = studio_mod.APS_PromptStudio()
    lenient = node.run(
        AI_PROFILE=_profile(store), text="make a prompt", target="anima_base",
        execution_mode="lenient", message_nonce="l1")
    stable_json = lenient["result"][2]
    stable = PromptSession.from_json(stable_json)
    with pytest.raises(ValueError):
        node.run(
            AI_PROFILE=store.get_profile("studio").node_payload(),
            text="rebuild strictly", target="anima_base",
            execution_mode="strict", prompt_session=stable_json,
            message_nonce="strict-switch")
    unchanged = PromptSession.from_json(stable_json)
    assert unchanged.id == stable.id
    assert unchanged.revision == stable.revision == 1


def test_successful_mode_switch_starts_new_strict_lineage(
        monkeypatch, store) -> None:
    SequenceGateway.responses = [
        "<PROMPT>A complete English image prompt.</PROMPT><SUMMARY>Done.</SUMMARY>",
        json.dumps({
            "content": {"scene_description": "A complete English image prompt.",
                        "characters": [], "environment": [], "style": []},
            "negative": "watermark",
        }),
    ]
    SequenceGateway.requests = []
    monkeypatch.setattr(studio_mod, "Gateway", SequenceGateway)
    node = studio_mod.APS_PromptStudio()
    lenient = node.run(
        AI_PROFILE=_profile(store), text="make a prompt", target="anima_base",
        execution_mode="lenient", message_nonce="l1")
    old = PromptSession.from_json(lenient["result"][2])
    strict = node.run(
        AI_PROFILE=store.get_profile("studio").node_payload(),
        text="rebuild this in strict mode", target="anima_base",
        execution_mode="strict", prompt_session=lenient["result"][2],
        message_nonce="s1")
    new = PromptSession.from_json(strict["result"][2])
    assert new.id != old.id
    assert new.execution_mode == "strict" and new.revision == 1


def test_previous_restores_prompt_without_gateway_call(monkeypatch, store) -> None:
    SequenceGateway.responses = [
        "<PROMPT>First complete English prompt.</PROMPT><SUMMARY>First.</SUMMARY>",
        "<PROMPT>Second complete English prompt.</PROMPT><SUMMARY>Second.</SUMMARY>",
    ]
    SequenceGateway.requests = []
    monkeypatch.setattr(studio_mod, "Gateway", SequenceGateway)
    node = studio_mod.APS_PromptStudio()
    first = node.run(AI_PROFILE=_profile(store), text="first", target="anima_base",
                     execution_mode="lenient", message_nonce="p1")
    second = node.run(
        AI_PROFILE=store.get_profile("studio").node_payload(), text="second",
        target="anima_base", execution_mode="lenient",
        prompt_session=first["result"][2], message_nonce="p2")
    restored = node.run(
        AI_PROFILE=store.get_profile("studio").node_payload(), text="",
        target="anima_base", execution_mode="lenient", session_action="previous",
        prompt_session=second["result"][2], message_nonce="restore")
    session = PromptSession.from_json(restored["result"][2])
    assert restored["result"][0] == "First complete English prompt."
    assert session.revision == 3
    assert len(SequenceGateway.requests) == 2


def test_strict_semantic_failure_does_not_request_creative_repair(
        monkeypatch, store) -> None:
    SequenceGateway.responses = [json.dumps({
        "content": {
            "scene_description": "A poster with watermark typography",
            "creative_notes": [], "characters": [], "control_tags": [],
            "series_tags": [], "artist_tags": [], "supplemental_tags": [],
            "style": [], "environment": [], "composition": "",
            "lighting": "", "negative_constraints": [],
        },
        "negative": "watermark",
    })]
    SequenceGateway.requests = []
    monkeypatch.setattr(studio_mod, "Gateway", SequenceGateway)
    with pytest.raises(ValueError, match="严格模式校验未通过"):
        studio_mod.APS_PromptStudio().run(
            AI_PROFILE=_profile(store), text="poster with watermark typography",
            target="anima_base", execution_mode="strict", message_nonce="conflict")
    assert len(SequenceGateway.requests) == 1


def test_lenient_identity_anchor_accepts_natural_word_insertion():
    bible = CharacterBible(
        character_id="char_ref", name="参考人物",
        traits=[CharacterTrait(
            name="hair_style", value="shoulder-length with bangs",
            category="stable", locked=True)])
    parsed = LenientPromptOutput(
        prompt="A girl with shoulder-length hair with soft bangs in the rain.",
        summary="", kind="tagged")
    report = studio_mod._validate_lenient_image(
        parsed, "anima", "turbo", bible, None, ReferenceManifest())
    assert report.valid


def test_lenient_identity_anchor_still_rejects_missing_distinctive_token():
    bible = CharacterBible(
        character_id="char_ref", name="参考人物",
        traits=[CharacterTrait(
            name="hair_style", value="side ponytail visible on right side",
            category="stable", locked=True)])
    parsed = LenientPromptOutput(
        prompt="A girl with a side ponytail visible on the left side.",
        summary="", kind="tagged")
    report = studio_mod._validate_lenient_image(
        parsed, "anima", "turbo", bible, None, ReferenceManifest())
    assert not report.valid
    assert any(issue.code == "lenient_identity_anchor_missing"
               for issue in report.issues)

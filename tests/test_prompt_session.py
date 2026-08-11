"""Persistent Prompt Studio domain state, exercised through its public interface."""
import json

import pytest

from aps.schemas.prompt_session import (
    MAX_CONVERSATION_MESSAGES,
    MAX_REVISIONS,
    PromptSession,
    SessionFingerprints,
)
from aps.schemas.base import SchemaError
from aps.services.prompt_session import broad_rewrite_requested, content_fingerprint


VALID = {"valid": True, "issues": [], "checks": ["non_empty"]}


def test_v3_defaults_to_empty_lenient_session() -> None:
    session = PromptSession()
    assert session.schema_version == "3.0"
    assert session.execution_mode == "lenient"
    assert session.current_payload_kind == "empty"
    assert session.has_current_state is False


def test_v2_workflow_state_resets_instead_of_becoming_editable_v3() -> None:
    old = {
        "schema_version": "2.0", "id": "old-session", "revision": 4,
        "target_family": "anima", "current_prompt": "old prompt",
        "current_plan": {"scene": "old"},
    }
    session = PromptSession.from_json(old)
    assert session.schema_version == "3.0"
    assert session.id != "old-session"
    assert session.revision == 0
    assert session.current_prompt == ""
    assert session.revisions == []


def test_freeform_commit_and_restore_share_atomic_revision_interface() -> None:
    session = PromptSession(
        target_family="anima", execution_mode="lenient")
    session.commit(
        {}, "first English prompt", VALID, "create", "created",
        expected_revision=0, message_id="m1", payload_kind="freeform",
        execution_mode="lenient", context_changes=["source:character_book"])
    session.commit(
        {}, "second English prompt", VALID, "make it warmer", "changed light",
        expected_revision=1, message_id="m2", payload_kind="freeform",
        execution_mode="lenient")
    assert session.has_current_state is True
    assert session.current_payload_kind == "freeform"
    assert session.revisions[0].context_changes == ["source:character_book"]
    assert session.revert_previous() is True
    assert session.current_prompt == "first English prompt"
    assert session.revision == 3


def test_broad_rewrite_authority_requires_explicit_user_wording():
    assert broad_rewrite_requested("整个重新设计，不用保留旧方案") is True
    assert broad_rewrite_requested("rebuild the entire plan") is True
    assert broad_rewrite_requested("把外套改成蓝色") is False


def test_session_commits_and_survives_workflow_roundtrip():
    session = PromptSession(target_family="anima", target_variant="base")
    session.commit(
        plan={"positive": "a girl in a red dress", "camera": "medium shot"},
        prompt="a girl in a red dress, medium shot",
        validation=VALID,
        user_instruction="东京雨夜里的女孩",
        change_summary="已建立第一版方案",
    )

    restored = PromptSession.from_json(json.dumps(session.to_json(), ensure_ascii=False))
    assert restored.revision == 1
    assert restored.current_plan["camera"] == "medium shot"
    assert restored.current_prompt == "a girl in a red dress, medium shot"
    assert restored.conversation[-1].content == "已建立第一版方案"


def test_invalid_revision_never_replaces_last_valid_state():
    session = PromptSession(target_family="anima")
    session.commit({"positive": "valid"}, "valid", VALID, "create", "created")
    before = session.to_json()

    with pytest.raises(ValueError, match="validation"):
        session.commit({"positive": "broken"}, "broken",
                       {"valid": False, "issues": []}, "change", "failed")

    assert session.to_json() == before


def test_commit_stages_every_field_before_swapping(monkeypatch):
    session = PromptSession(target_family="anima", current_plan={"old": True},
                            current_prompt="old", revision=1)
    before = session.to_json()

    def fail_message(*args, **kwargs):
        raise RuntimeError("conversation failed")

    monkeypatch.setattr("aps.schemas.prompt_session.ChatMessage", fail_message)
    with pytest.raises(RuntimeError, match="conversation failed"):
        session.commit({"new": True}, "new", VALID, "change", "summary")
    assert session.to_json() == before


def test_commit_rechecks_expected_revision_before_swap():
    session = PromptSession(target_family="anima")
    session.commit({"v": 1}, "one", VALID, "create", "v1", expected_revision=0)
    before = session.to_json()
    with pytest.raises(ValueError, match="CAS"):
        session.commit({"v": 2}, "two", VALID, "change", "v2",
                       expected_revision=0)
    assert session.to_json() == before


def test_restore_creates_new_revision_without_destroying_history():
    session = PromptSession(target_family="anima")
    session.commit({"clothing": "red dress"}, "red dress", VALID, "create", "v1")
    session.commit({"clothing": "black dress"}, "black dress", VALID, "black", "v2")

    restored = session.revert_previous()
    assert restored is True
    assert session.revision == 3
    assert session.current_plan == {"clothing": "red dress"}
    assert session.current_prompt == "red dress"
    assert [item.revision for item in session.revisions] == [1, 2, 3]
    assert session.revisions[-1].parent_revision == 1
    assert session.revisions[1].plan == {"clothing": "black dress"}


def test_revision_snapshot_metadata_and_plan_are_stable_after_later_commits():
    session = PromptSession(target_family="anima")
    fingerprints = SessionFingerprints(
        target_signature="anima:base", model_core_hash="core-v1",
        source_hashes={"character_bible": "book-v1"},
        skill_hashes={"anima_expand": "skill-v1"})
    first_plan = {"clothing": "red dress"}
    session.commit(
        first_plan, "red dress", VALID, "create", "v1",
        message_id="msg-1", fingerprints=fingerprints,
        renderer_signature="anima-renderer@1")
    first_plan["clothing"] = "mutated outside"
    first = session.revisions[0]
    session.commit(
        {"clothing": "blue dress"}, "blue dress", VALID, "blue", "v2",
        message_id="msg-2", requested_paths=["characters/0/clothing"],
        expected_revision=1)

    assert first.plan == {"clothing": "red dress"}
    assert first.parent_revision == 0
    assert first.message_id == "msg-1"
    assert first.renderer_signature == "anima-renderer@1"
    assert first.model_core_hash == "core-v1"
    assert first.skill_hashes == {"anima_expand": "skill-v1"}
    assert session.revisions[1].requested_paths == ["characters/0/clothing"]
    with pytest.raises(TypeError, match="immutable"):
        first.plan["clothing"] = "history tampering"
    with pytest.raises(AttributeError, match="immutable"):
        first.prompt = "history tampering"
    with pytest.raises(TypeError, match="immutable"):
        session.revisions[1].requested_paths.append("camera")


def test_message_nonce_and_fingerprint_mismatch_are_explicit_session_state():
    session = PromptSession(target_family="anima")
    fingerprints = SessionFingerprints(
        target_signature="anima:base", model_core_hash="core-v1",
        source_hashes={"storyboard": "story-v1"})
    session.commit(
        {"scene": "Tokyo"}, "Tokyo", VALID, "create", "v1",
        message_id="message-123", fingerprints=fingerprints)

    assert session.has_processed_message("message-123") is True
    assert session.has_processed_message("message-456") is False
    changed = SessionFingerprints(
        target_signature="anima:base", model_core_hash="core-v1",
        source_hashes={"storyboard": "story-v2"})
    assert session.fingerprint_mismatches(changed) == ["source:storyboard"]
    changed_core = SessionFingerprints(
        target_signature="anima:base", model_core_hash="core-v2",
        source_hashes={"storyboard": "story-v1"},
        skill_hashes={"editorial": "skill-v2"})
    assert session.fingerprint_mismatches(changed_core) == [
        "model_core", "skill:editorial"]


def test_session_history_is_bounded_without_mutating_retained_snapshots():
    session = PromptSession(target_family="anima")
    for number in range(1, MAX_REVISIONS + 4):
        session.commit(
            {"value": number}, str(number), VALID, f"message {number}",
            f"v{number}", message_id=f"msg-{number}",
            expected_revision=number - 1)
    assert len(session.revisions) == MAX_REVISIONS
    assert session.revisions[-1].revision == MAX_REVISIONS + 3
    assert len(session.conversation) <= MAX_CONVERSATION_MESSAGES

    restored = PromptSession.from_json({
        **session.to_json(),
        "revisions": [session.revisions[-1].to_json()
                      for _ in range(MAX_REVISIONS + 5)],
        "conversation": [{"role": "user", "content": str(index)}
                         for index in range(MAX_CONVERSATION_MESSAGES + 5)],
    })
    assert len(restored.revisions) == MAX_REVISIONS
    assert len(restored.conversation) == MAX_CONVERSATION_MESSAGES


def test_legacy_v1_session_resets_to_empty_v3_state():
    legacy = {
        "schema_version": "1.0", "id": "psess_legacy",
        "target_family": "anima", "target_variant": "base",
        "current_plan": {"scene": "Tokyo"}, "current_prompt": "Tokyo",
        "revision": 1, "conversation": [], "locked_constraints": [],
        "validation": VALID,
        "revisions": [{"revision": 1, "plan": {"scene": "Tokyo"},
                       "prompt": "Tokyo", "validation": VALID,
                       "user_instruction": "create", "change_summary": "v1"}],
    }
    restored = PromptSession.from_json(legacy)
    assert restored.schema_version == "3.0"
    assert restored.current_plan == {}
    assert restored.current_prompt == ""
    assert restored.revisions == []
    assert restored.last_processed_message_id == ""
    assert restored.fingerprint_state == "bound"


def test_source_schema_version_is_part_of_the_authoritative_fingerprint():
    v1 = {"schema_version": "1.0", "character_id": "alice"}
    v2 = {"schema_version": "2.0", "character_id": "alice"}
    assert content_fingerprint(v1) != content_fingerprint(v2)


def test_future_or_malformed_session_is_rejected_instead_of_silently_downgraded():
    with pytest.raises(SchemaError, match="future schema_version"):
        PromptSession.from_json({"schema_version": "4.0", "current_plan": {}})
    with pytest.raises(SchemaError, match=r"revisions\[0\]"):
        PromptSession.from_json({
            "schema_version": "3.0", "revisions": ["not a revision"]})

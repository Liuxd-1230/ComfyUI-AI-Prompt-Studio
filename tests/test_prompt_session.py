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
from aps.services.prompt_session import (
    apply_plan_patch,
    broad_rewrite_requested,
    content_fingerprint,
)


VALID = {"valid": True, "issues": [], "checks": ["non_empty"]}


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


def test_legacy_v1_session_migrates_to_v2_without_losing_current_state():
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
    assert restored.schema_version == "2.0"
    assert restored.current_plan == {"scene": "Tokyo"}
    assert restored.revisions[0].revision_id
    assert restored.revisions[0].parent_revision == 0
    assert restored.last_processed_message_id == ""
    assert restored.fingerprint_state == "legacy_unbound"


def test_source_schema_version_is_part_of_the_authoritative_fingerprint():
    v1 = {"schema_version": "1.0", "character_id": "alice"}
    v2 = {"schema_version": "2.0", "character_id": "alice"}
    assert content_fingerprint(v1) != content_fingerprint(v2)


def test_future_or_malformed_session_is_rejected_instead_of_silently_downgraded():
    with pytest.raises(SchemaError, match="future schema_version"):
        PromptSession.from_json({"schema_version": "3.0", "current_plan": {}})
    with pytest.raises(SchemaError, match=r"revisions\[0\]"):
        PromptSession.from_json({
            "schema_version": "2.0", "revisions": ["not a revision"]})


def test_minimal_patch_changes_only_requested_path():
    current = {
        "characters": [{"identity": "Alice", "clothing": "red dress"}],
        "environment": "Tokyo rain", "camera": "medium shot",
    }
    patch = {"base_revision": 1, "scope": "minimal", "changes": [{
        "path": "characters/0/clothing", "action": "replace",
        "value": "white trench coat",
    }]}
    updated = apply_plan_patch(current, patch, current_revision=1,
                               locked_paths=["characters/0/identity"])
    assert updated == {
        "characters": [{"identity": "Alice", "clothing": "white trench coat"}],
        "environment": "Tokyo rain", "camera": "medium shot",
    }
    assert current["characters"][0]["clothing"] == "red dress"


def test_invalid_or_stale_patch_cannot_mutate_current_plan():
    current = {"identity": "Alice", "camera": "medium"}
    with pytest.raises(ValueError, match="stale"):
        apply_plan_patch(current, {"base_revision": 1, "changes": []},
                         current_revision=2)
    with pytest.raises(ValueError, match="locked"):
        apply_plan_patch(current, {"base_revision": 2, "changes": [{
            "path": "identity", "action": "replace", "value": "Bob"}]},
            current_revision=2, locked_paths=["identity"])
    assert current == {"identity": "Alice", "camera": "medium"}


def test_explicit_broad_rebuild_is_allowed_but_minimal_rebuild_is_rejected():
    current = {"character": "Alice", "environment": "Tokyo"}
    rebuilt = {"character": "Alice", "environment": "Mars", "camera": "wide"}
    updated = apply_plan_patch(current, {
        "base_revision": 3, "scope": "broad", "changes": [],
        "rebuild_plan": rebuilt}, current_revision=3)
    assert updated == rebuilt
    with pytest.raises(ValueError, match="broad"):
        apply_plan_patch(current, {
            "base_revision": 3, "scope": "minimal", "changes": [],
            "rebuild_plan": rebuilt}, current_revision=3)


def test_scoped_broad_rebuild_preserves_bundle_and_locked_fields():
    current = {
        "prompt_plan": {"positive": "old"},
        "model_plan": {"family": "anima", "content": {"scene": "Tokyo"}},
        "generation_profile": {"steps": 28},
    }
    rebuilt = {"model_plan": {
        "family": "anima", "content": {"scene": "Mars", "camera": "wide"}}}
    updated = apply_plan_patch(
        current, {"base_revision": 2, "scope": "broad", "changes": [],
                  "rebuild_plan": rebuilt}, current_revision=2,
        allowed_roots=["model_plan"], locked_paths=["model_plan/family"])
    assert updated["model_plan"]["content"]["scene"] == "Mars"
    assert updated["prompt_plan"] == current["prompt_plan"]
    assert updated["generation_profile"] == current["generation_profile"]

    rebuilt["model_plan"]["family"] = "generic"
    with pytest.raises(ValueError, match="locked"):
        apply_plan_patch(
            current, {"base_revision": 2, "scope": "broad", "changes": [],
                      "rebuild_plan": rebuilt}, current_revision=2,
            allowed_roots=["model_plan"], locked_paths=["model_plan/family"])

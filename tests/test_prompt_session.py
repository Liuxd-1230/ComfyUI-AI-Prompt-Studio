"""Persistent Prompt Studio domain state, exercised through its public interface."""
import json

import pytest

from aps.schemas.prompt_session import PromptSession
from aps.services.prompt_session import apply_plan_patch, broad_rewrite_requested


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


def test_revert_restores_plan_and_prompt_together():
    session = PromptSession(target_family="anima")
    session.commit({"clothing": "red dress"}, "red dress", VALID, "create", "v1")
    session.commit({"clothing": "black dress"}, "black dress", VALID, "black", "v2")

    restored = session.revert_previous()
    assert restored is True
    assert session.revision == 1
    assert session.current_plan == {"clothing": "red dress"}
    assert session.current_prompt == "red dress"


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

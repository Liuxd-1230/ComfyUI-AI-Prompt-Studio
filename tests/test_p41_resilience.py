"""P4.1 resilience contracts exercised at the Gateway/session public seam."""
from __future__ import annotations

import json
import logging

import pytest

from aps.schemas.anima import AnimaPromptPlan
from aps.schemas.profile import AIProfile
from aps.schemas.prompt_session import PromptSession, SessionFingerprints
from aps.schemas.results import LLMResult
from aps.services.prompt_session import assert_session_fingerprints, request_changeset


def _session() -> PromptSession:
    plan = AnimaPromptPlan(scene_description="A rainy street.")
    return PromptSession(
        target_family="anima", target_variant="base", revision=1,
        current_prompt="A rainy street.",
        current_plan={"model_plan": {"content": plan.to_json(), "negative": ""}})


def _valid_changeset() -> dict[str, object]:
    return {
        "base_revision": 1, "plan_type": "anima",
        "change_category": "minimal_refine", "intent_scope": ["content/lighting"],
        "requested_changes": [{"path": "content/lighting", "operation": "set",
                                "value_json": '"blue hour"',
                                "reason": "user requested lighting"}],
        "dependent_changes": [], "invalidated_facts": [],
        "constraint_conflicts": [], "summary": "change lighting",
    }


def test_malformed_changeset_is_retried_once_then_declared_paths_are_authorized() -> None:
    malformed = _valid_changeset()
    malformed["intent_scope"] = []
    malformed["requested_changes"] = [
        *malformed["requested_changes"], *malformed["requested_changes"]]

    class Gateway:
        calls = 0

        def generate(self, profile, api_key, req):
            del profile, api_key
            type(self).calls += 1
            payload = malformed if type(self).calls == 1 else _valid_changeset()
            return LLMResult(text=json.dumps(payload))

    result = request_changeset(
        Gateway(), AIProfile(timeout=30), "test-key", _session(), "make it blue")
    assert result.requested_changes[0].path == "content/lighting"
    assert result.approved_requested_paths == ["content/lighting"]
    assert Gateway.calls == 2


def test_changeset_retry_failure_logs_and_reports_bounded_raw(
        caplog: pytest.LogCaptureFixture) -> None:
    raw = "not-json:" + "x" * 900

    class Gateway:
        calls = 0

        def generate(self, profile, api_key, req):
            del profile, api_key, req
            type(self).calls += 1
            return LLMResult(text=raw)

    with caplog.at_level(logging.WARNING, logger="ai_prompt_studio.prompt_session"):
        with pytest.raises(ValueError) as exc_info:
            request_changeset(
                Gateway(), AIProfile(timeout=30), "test-key", _session(), "change")
    message = str(exc_info.value)
    assert Gateway.calls == 2
    assert "模型原始输出（截断）" in message
    assert len(message) < 900
    assert raw[:120] in caplog.text


def test_strict_changeset_uses_one_declared_proposal_call() -> None:
    class Gateway:
        calls = 0
        requests = []

        def generate(self, profile, api_key, req):
            del profile, api_key
            type(self).calls += 1
            type(self).requests.append(req)
            return LLMResult(text=json.dumps(_valid_changeset()))

    result = request_changeset(
        Gateway(), AIProfile(timeout=30), "test-key", _session(),
        "Change the lighting to blue hour.")
    assert result.approved_requested_paths == ["content/lighting"]
    assert Gateway.calls == 1
    system = Gateway.requests[0].system
    assert "content/characters/0/required_traits/3" in system
    assert "Never prefix a path with current_plan" in system
    assert "dependent_changes must be []" in system
    task_data = Gateway.requests[0].messages[0].content
    assert '"available_existing_paths"' in task_data
    assert '"content/lighting"' in task_data
    assert '"content/characters/0/required_traits/0"' not in task_data


def test_changeset_unknown_current_plan_prefix_is_retried() -> None:
    bad = _valid_changeset()
    bad["intent_scope"] = ["current_plan/content/lighting"]
    bad["requested_changes"] = [{
        "path": "current_plan/content/lighting", "operation": "set",
        "value_json": '"blue hour"', "reason": "wrong wrapper prefix"}]

    class Gateway:
        calls = 0

        def generate(self, profile, api_key, req):
            del profile, api_key, req
            type(self).calls += 1
            payload = bad if type(self).calls == 1 else _valid_changeset()
            return LLMResult(text=json.dumps(payload))

    result = request_changeset(
        Gateway(), AIProfile(timeout=30), "test-key", _session(), "make it blue")
    assert result.requested_changes[0].path == "content/lighting"
    assert Gateway.calls == 2


def test_changeset_nonexistent_leaf_is_retried_before_transaction() -> None:
    bad = _valid_changeset()
    bad["intent_scope"] = ["content/characters/0/lighting"]
    bad["requested_changes"] = [{
        "path": "content/characters/0/lighting", "operation": "set",
        "value_json": '"blue hour"', "reason": "field is at the wrong depth"}]

    class Gateway:
        calls = 0

        def generate(self, profile, api_key, req):
            del profile, api_key, req
            type(self).calls += 1
            payload = bad if type(self).calls == 1 else _valid_changeset()
            return LLMResult(text=json.dumps(payload))

    result = request_changeset(
        Gateway(), AIProfile(timeout=30), "test-key", _session(), "make it blue")
    assert result.requested_changes[0].path == "content/lighting"
    assert Gateway.calls == 2


def test_fingerprint_error_names_only_currently_available_recovery_actions() -> None:
    session = _session()
    session.fingerprint_state = "bound"
    session.fingerprints = SessionFingerprints(target_signature="anima:base:tags")
    with pytest.raises(ValueError) as exc_info:
        assert_session_fingerprints(
            session, SessionFingerprints(target_signature="anima:turbo:tags"))
    message = str(exc_info.value)
    assert "原因：target_signature" in message
    assert "新会话" in message and "恢复上一版" in message
    assert "自动 Rebase 尚未实现" in message
    assert "后续 Rebase/Migration 必须显式处理" not in message

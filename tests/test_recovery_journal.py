"""P5 durable Recovery Journal and commit-time CAS behavior."""
from __future__ import annotations

import pytest

from aps.domain.recovery_journal import (
    DurableRecoveryJournal,
    JournalConflict,
    MemoryRecoveryJournal,
)
from aps.schemas.prompt_session import PromptSession


VALID = {"valid": True, "issues": []}


def test_commit_can_publish_recoverable_snapshot_through_journal_interface() -> None:
    journal = MemoryRecoveryJournal()
    session = PromptSession(target_family="anima")
    session.commit(
        {"plan": "v1"}, "prompt v1", VALID, "create", "created",
        expected_revision=0, transaction_id="tx-1", node_instance_id="node-7",
        recovery_journal=journal)

    entry = journal.latest(session.id, "node-7")
    assert entry is not None
    assert entry.transaction_id == "tx-1"
    assert entry.base_revision == 0 and entry.result_revision == 1
    assert entry.session_snapshot["current_prompt"] == "prompt v1"
    entry.session_snapshot["current_prompt"] = "tampered outside"
    assert journal.latest(session.id, "node-7").session_snapshot[
        "current_prompt"] == "prompt v1"


def test_journal_rejects_stale_branch_for_same_session_and_node() -> None:
    journal = MemoryRecoveryJournal()
    session = PromptSession(target_family="anima")
    session.commit(
        {"plan": "v1"}, "v1", VALID, "create", "created",
        expected_revision=0, transaction_id="tx-1", node_instance_id="node-7",
        recovery_journal=journal)
    stale = PromptSession.from_json(session.to_json())
    session.commit(
        {"plan": "v2"}, "v2", VALID, "change", "v2",
        expected_revision=1, transaction_id="tx-2", node_instance_id="node-7",
        recovery_journal=journal)
    with pytest.raises(JournalConflict, match="stale"):
        stale.commit(
            {"plan": "branch"}, "branch", VALID, "change", "branch",
            expected_revision=1, transaction_id="tx-stale",
            node_instance_id="node-7", recovery_journal=journal)
    assert stale.revision == 1


def test_revision_records_actual_repair_count() -> None:
    session = PromptSession(target_family="anima")
    session.commit(
        {"plan": "fixed"}, "fixed", VALID, "create", "fixed once",
        expected_revision=0, repair_count=1)
    assert session.revisions[-1].repair_count == 1
    assert session.revisions[-1].repair_attempted is True


def test_journal_write_failure_leaves_stable_session_unchanged() -> None:
    class BrokenJournal:
        def record_success(self, _entry) -> None:
            raise OSError("disk unavailable")

    session = PromptSession(target_family="anima")
    before = session.to_json()
    with pytest.raises(OSError, match="disk unavailable"):
        session.commit(
            {"plan": "candidate"}, "candidate", VALID, "create", "candidate",
            expected_revision=0, recovery_journal=BrokenJournal())
    assert session.to_json() == before


def test_durable_journal_survives_new_adapter_instance(tmp_path) -> None:
    path = tmp_path / "recovery-journal.json"
    first = DurableRecoveryJournal(path)
    session = PromptSession(target_family="anima")
    session.commit(
        {"plan": "v1"}, "prompt v1", VALID, "create", "created",
        expected_revision=0, transaction_id="tx-durable-1",
        node_instance_id="node-durable", recovery_journal=first)

    restored = DurableRecoveryJournal(path).latest(
        session.id, "node-durable")

    assert restored is not None
    assert restored.result_revision == 1
    assert restored.session_snapshot["current_prompt"] == "prompt v1"


def test_durable_journal_cas_rejects_late_writer_across_instances(tmp_path) -> None:
    path = tmp_path / "recovery-journal.json"
    first = DurableRecoveryJournal(path)
    second = DurableRecoveryJournal(path)
    session = PromptSession(target_family="anima")
    session.commit(
        {"plan": "v1"}, "v1", VALID, "create", "created",
        expected_revision=0, transaction_id="tx-1",
        node_instance_id="node-7", recovery_journal=first)
    stale = PromptSession.from_json(session.to_json())
    session.commit(
        {"plan": "v2"}, "v2", VALID, "change", "v2",
        expected_revision=1, transaction_id="tx-2",
        node_instance_id="node-7", recovery_journal=second)

    with pytest.raises(JournalConflict, match="stale"):
        stale.commit(
            {"plan": "branch"}, "branch", VALID, "change", "branch",
            expected_revision=1, transaction_id="tx-stale",
            node_instance_id="node-7",
            recovery_journal=DurableRecoveryJournal(path))
    assert stale.revision == 1


def test_durable_journal_quarantines_corrupt_file(tmp_path) -> None:
    path = tmp_path / "recovery-journal.json"
    path.write_text("{not-json", encoding="utf-8")

    journal = DurableRecoveryJournal(path)

    assert journal.latest("missing", "node") is None
    assert list(tmp_path.glob("recovery-journal.corrupt-*.json"))


def test_durable_journal_retains_most_recent_sessions_not_highest_revisions(
        tmp_path) -> None:
    path = tmp_path / "recovery-journal.json"
    journal = DurableRecoveryJournal(path, max_entries=2)
    old = PromptSession(target_family="anima")
    for revision in range(1, 4):
        old.commit(
            {"plan": f"old-{revision}"}, f"old-{revision}", VALID,
            "change", f"old-{revision}", expected_revision=revision - 1,
            transaction_id=f"tx-old-{revision}", node_instance_id="old-node",
            recovery_journal=journal)

    recent_a = PromptSession(target_family="anima")
    recent_a.commit(
        {"plan": "recent-a"}, "recent-a", VALID, "create", "recent-a",
        expected_revision=0, transaction_id="tx-recent-a",
        node_instance_id="recent-a-node", recovery_journal=journal)
    recent_b = PromptSession(target_family="anima")
    recent_b.commit(
        {"plan": "recent-b"}, "recent-b", VALID, "create", "recent-b",
        expected_revision=0, transaction_id="tx-recent-b",
        node_instance_id="recent-b-node", recovery_journal=journal)

    reloaded = DurableRecoveryJournal(path, max_entries=2)
    assert reloaded.latest(old.id, "old-node") is None
    assert reloaded.latest(recent_a.id, "recent-a-node") is not None
    assert reloaded.latest(recent_b.id, "recent-b-node") is not None

"""P4.1 clean Recovery Journal interface before P5 persistence wiring."""
from __future__ import annotations

import pytest

from aps.domain.recovery_journal import (
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

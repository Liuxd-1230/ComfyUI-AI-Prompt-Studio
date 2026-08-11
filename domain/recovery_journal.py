"""Recovery Journal interface reserved for workflow writeback recovery."""
from __future__ import annotations

import copy
import dataclasses
import threading
from typing import Protocol


class JournalConflict(ValueError):
    """A late branch attempted to replace a newer journal result."""


@dataclasses.dataclass(frozen=True)
class RecoveryJournalEntry:
    session_id: str
    node_instance_id: str
    transaction_id: str
    base_revision: int
    result_revision: int
    session_snapshot: dict[str, object]


class RecoveryJournal(Protocol):
    def record_success(self, entry: RecoveryJournalEntry) -> None: ...

    def latest(self, session_id: str,
               node_instance_id: str) -> RecoveryJournalEntry | None: ...

    def discard(self, session_id: str, node_instance_id: str) -> None: ...


class MemoryRecoveryJournal:
    """Thread-safe executable reference implementation for the journal contract.

    It is intentionally not the production persistence backend. P5 may replace it
    with durable storage without changing PromptSession's commit seam.
    """

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], RecoveryJournalEntry] = {}
        self._lock = threading.RLock()

    def record_success(self, entry: RecoveryJournalEntry) -> None:
        key = (entry.session_id, entry.node_instance_id)
        with self._lock:
            latest = self._entries.get(key)
            if latest is not None and entry.base_revision != latest.result_revision:
                raise JournalConflict(
                    "stale recovery journal transaction: "
                    f"base v{entry.base_revision}, latest v{latest.result_revision}")
            self._entries[key] = copy.deepcopy(entry)

    def latest(self, session_id: str,
               node_instance_id: str) -> RecoveryJournalEntry | None:
        with self._lock:
            entry = self._entries.get((session_id, node_instance_id))
            return copy.deepcopy(entry) if entry is not None else None

    def discard(self, session_id: str, node_instance_id: str) -> None:
        with self._lock:
            self._entries.pop((session_id, node_instance_id), None)

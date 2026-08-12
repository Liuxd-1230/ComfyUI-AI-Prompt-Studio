"""Recovery Journal interface reserved for workflow writeback recovery."""
from __future__ import annotations

import copy
import dataclasses
import json
import threading
import time
from pathlib import Path
from typing import Any, Protocol


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


_PATH_LOCKS: dict[str, threading.RLock] = {}
_PATH_LOCKS_GUARD = threading.RLock()


def _path_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.RLock())


class DurableRecoveryJournal:
    """Atomic, bounded JSON adapter for crash recovery and commit-time CAS."""

    SCHEMA_VERSION = 1

    def __init__(self, path: Path | str, max_entries: int = 100) -> None:
        self.path = Path(path)
        self.max_entries = max(1, int(max_entries))
        self._lock = _path_lock(self.path)

    def record_success(self, entry: RecoveryJournalEntry) -> None:
        self._validate_entry(entry)
        key = (entry.session_id, entry.node_instance_id)
        with self._lock:
            entries = self._read_entries()
            latest = entries.get(key)
            if latest is not None and entry.base_revision != latest.result_revision:
                raise JournalConflict(
                    "stale recovery journal transaction: "
                    f"base v{entry.base_revision}, latest v{latest.result_revision}")
            # Dict order is the durable recency index. Reinsert an updated key so
            # a high-revision old session cannot starve newer low-revision ones.
            entries.pop(key, None)
            entries[key] = copy.deepcopy(entry)
            retained = list(entries.values())[-self.max_entries:]
            self._write_entries(retained)

    def latest(self, session_id: str,
               node_instance_id: str) -> RecoveryJournalEntry | None:
        with self._lock:
            entry = self._read_entries().get((str(session_id), str(node_instance_id)))
            return copy.deepcopy(entry) if entry is not None else None

    def discard(self, session_id: str, node_instance_id: str) -> None:
        key = (str(session_id), str(node_instance_id))
        with self._lock:
            entries = self._read_entries()
            if entries.pop(key, None) is not None:
                self._write_entries(list(entries.values()))

    @staticmethod
    def _validate_entry(entry: RecoveryJournalEntry) -> None:
        if not entry.session_id or not entry.node_instance_id:
            raise ValueError("recovery journal 需要 session_id 与 node_instance_id")
        if entry.result_revision != entry.base_revision + 1:
            raise ValueError("recovery journal revision lineage 非法")
        snapshot = entry.session_snapshot
        if (not isinstance(snapshot, dict)
                or snapshot.get("id") != entry.session_id
                or int(snapshot.get("revision", -1)) != entry.result_revision):
            raise ValueError("recovery journal snapshot 与 entry 不一致")

    def _read_entries(self) -> dict[tuple[str, str], RecoveryJournalEntry]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if (not isinstance(payload, dict)
                    or payload.get("schema_version") != self.SCHEMA_VERSION
                    or not isinstance(payload.get("entries"), list)):
                raise ValueError("journal envelope invalid")
            result: dict[tuple[str, str], RecoveryJournalEntry] = {}
            for raw in payload["entries"]:
                entry = RecoveryJournalEntry(**raw)
                self._validate_entry(entry)
                result[(entry.session_id, entry.node_instance_id)] = entry
            return result
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            self._quarantine_corrupt_file()
            return {}

    def _write_entries(self, entries: list[RecoveryJournalEntry]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "schema_version": self.SCHEMA_VERSION,
            "entries": [dataclasses.asdict(entry) for entry in entries],
        }
        temp_path = self.path.with_name(self.path.name + ".tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self.path)

    def _quarantine_corrupt_file(self) -> None:
        if not self.path.exists():
            return
        stamp = time.strftime("%Y%m%d-%H%M%S")
        quarantine = self.path.with_name(
            f"{self.path.stem}.corrupt-{stamp}{self.path.suffix}")
        counter = 1
        while quarantine.exists():
            quarantine = self.path.with_name(
                f"{self.path.stem}.corrupt-{stamp}-{counter}{self.path.suffix}")
            counter += 1
        self.path.replace(quarantine)

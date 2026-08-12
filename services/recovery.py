"""Production Recovery Journal adapter for Prompt Studio nodes and routes."""
from __future__ import annotations

import threading
from pathlib import Path

from ..domain.recovery_journal import DurableRecoveryJournal
from ..server.config_store import default_config_dir

_LOCK = threading.RLock()
_JOURNALS: dict[str, DurableRecoveryJournal] = {}


def get_recovery_journal(base_dir: Path | str | None = None) -> DurableRecoveryJournal:
    """Return the process adapter while keeping durable state in ComfyUI user data."""
    directory = Path(base_dir) if base_dir is not None else default_config_dir()
    path = directory / "recovery-journal.json"
    key = str(path.resolve())
    with _LOCK:
        return _JOURNALS.setdefault(key, DurableRecoveryJournal(path))

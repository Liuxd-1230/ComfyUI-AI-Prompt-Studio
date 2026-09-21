"""Production Recovery Journal adapter for Prompt Studio nodes and routes."""
from __future__ import annotations

import threading
from pathlib import Path

from ..domain.recovery_journal import DurableRecoveryJournal
from ..server.config_store import get_store

_LOCK = threading.RLock()
_JOURNALS: dict[str, DurableRecoveryJournal] = {}


def get_recovery_journal(base_dir: Path | str | None = None) -> DurableRecoveryJournal:
    """恢复日志的唯一目录来源：ConfigStore 的数据目录。

    此前节点走 default_config_dir()、路由走 store.config_dir()；一旦 store 被
    注入非默认目录（测试或自定义数据目录），节点写 A 文件、路由读 B 文件，
    UI 永远 found:False 且 discard 变成静默空操作。
    """
    directory = Path(base_dir) if base_dir is not None else get_store().config_dir()
    path = directory / "recovery-journal.json"
    key = str(path.resolve())
    with _LOCK:
        return _JOURNALS.setdefault(key, DurableRecoveryJournal(path))

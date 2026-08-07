"""密钥存储与脱敏。

安全规则（docs/decisions.md D3）：
- 密钥只存用户目录下 <pkg>/secrets.json；
- 前端/工作流/日志永远只见脱敏值（mask_key）；
- 配置文件与密钥文件分离，避免误提交。
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path


def mask_key(key: str) -> str:
    """sk-abcdef1234... -> sk-***1234（保留前 3 与后 4；过短全部打码）。"""
    if not key:
        return ""
    key = str(key).strip()
    if len(key) <= 8:
        return "***"
    return key[:3] + "***" + key[-4:]


def validate_profile_id(profile_id: str) -> str:
    """白名单校验档案 id，阻止路径穿越/注入。非法时抛 ValueError（可读信息）。"""
    if not profile_id or not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", profile_id):
        raise ValueError(
            f"非法 profile id {profile_id!r}：只允许字母/数字/下划线/连字符，1-64 个字符"
        )
    return profile_id


class SecretStore:
    """按 profile_id 存储/读取密钥。文件权限与路径由调用方负责。"""

    def __init__(self, path):
        self._path = Path(path)
        self._lock = threading.RLock()
        self._data = self._load()

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 - 损坏则从空开始
                return {}
        return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(self._path.name + ".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path)

    def set(self, profile_id: str, key: str) -> None:
        pid = validate_profile_id(profile_id)
        with self._lock:
            self._data[pid] = str(key).strip()
            self._save()

    def get(self, profile_id: str):
        pid = validate_profile_id(profile_id)
        with self._lock:
            return self._data.get(pid)

    def delete(self, profile_id: str) -> None:
        pid = validate_profile_id(profile_id)
        with self._lock:
            if pid in self._data:
                del self._data[pid]
                self._save()

    def masked(self, profile_id: str) -> str:
        key = self.get(profile_id)
        return mask_key(key) if key else ""

    def has(self, profile_id: str) -> bool:
        pid = validate_profile_id(profile_id)
        with self._lock:
            return bool(self._data.get(pid))

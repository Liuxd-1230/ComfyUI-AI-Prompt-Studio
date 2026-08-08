"""配置存储：profiles / 默认档案 / 能力缓存 / 请求日志（脱敏）。

存储位置：ComfyUI 用户目录下 <pkg>/config.json（folder_paths.user_directory），
测试/独立环境回退到 ~/.comfyui_ai_prompt_studio。密钥在 secrets.json（SecretStore）。
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..schemas.profile import AIProfile
from ..services.secrets import SecretStore, mask_key, validate_profile_id

logger = logging.getLogger("ai_prompt_studio.config")

PACKAGE_NAME = "ai_prompt_studio"

# 允许从前端 payload 写入的 profile 字段（白名单，排除 api_key_ref 等内部字段）
ALLOWED_PROFILE_KEYS = {f.name for f in dataclasses.fields(AIProfile)} - {"api_key_ref"}


def _persistable(profile: AIProfile) -> Dict[str, Any]:
    """落盘用 dict：纵深防御，任何密钥引用字段都不写入 config.json。"""
    data = profile.to_json()
    data.pop("api_key_ref", None)
    return data


def _capability_fingerprint(profile: AIProfile) -> str:
    fields = {key: getattr(profile, key, None) for key in (
        "provider", "base_url", "model", "protocol", "vision_base_url",
        "vision_model", "vision_profile_id", "supports_vision", "supports_files")}
    fields["active_probe_version"] = 2
    raw = json.dumps(fields, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def default_config_dir() -> Path:
    """设置文件目录：优先 ComfyUI 用户目录，否则用户主目录。"""
    try:
        import folder_paths  # type: ignore

        return Path(folder_paths.user_directory) / PACKAGE_NAME
    except Exception:  # noqa: BLE001 - 无 ComfyUI 环境
        return Path.home() / ".comfyui_ai_prompt_studio"


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


class ConfigStore:
    """单进程配置存储（线程安全）。"""

    def __init__(self, base_dir: Optional[Path | str] = None):
        self.base_dir = Path(base_dir) if base_dir else default_config_dir()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._config_path = self.base_dir / "config.json"
        self._secrets = SecretStore(self.base_dir / "secrets.json")
        self._config: Dict[str, Any] = self._read_json(self._config_path, {
            "profiles": [],
            "default_profile_id": "",
            "capability_cache": {},
            "request_log": [],
            "settings": {},
        })

    # ---------- IO ----------
    def _read_json(self, path: Path, default: Any) -> Any:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 - 损坏回退默认
                logger.warning("配置读取失败，使用默认：%s", path)
        return default

    def _save_config(self) -> None:
        with self._lock:
            _atomic_write(self._config_path, self._config)

    def config_dir(self) -> Path:
        return self.base_dir

    # ---------- profile CRUD ----------
    def _profiles_list(self) -> List[Dict[str, Any]]:
        return self._config.setdefault("profiles", [])

    def list_profiles(self) -> List[Dict[str, Any]]:
        """返回档案列表，密钥只给脱敏值。"""
        result = []
        for p in self._profiles_list():
            item = dict(p)
            item["api_key_masked"] = self._secrets.masked(item.get("profile_id", ""))
            result.append(item)
        return result

    def get_profile(self, profile_id: str) -> Optional[AIProfile]:
        pid = validate_profile_id(profile_id)
        for p in self._profiles_list():
            if p.get("profile_id") == pid:
                return AIProfile.from_json(p)
        return None

    def get_default_profile(self) -> Optional[AIProfile]:
        pid = self._config.get("default_profile_id", "")
        if pid:
            return self.get_profile(pid)
        profiles = self._profiles_list()
        if profiles:
            return self.get_profile(profiles[0]["profile_id"])
        return None

    def set_default_profile(self, profile_id: str) -> None:
        pid = validate_profile_id(profile_id)
        if not self.get_profile(pid):
            raise KeyError(f"profile 不存在: {pid}")
        with self._lock:
            self._config["default_profile_id"] = pid
            self._save_config()

    def create_profile(self, data: Dict[str, Any]) -> AIProfile:
        clean = {k: v for k, v in (data or {}).items() if k in ALLOWED_PROFILE_KEYS}
        profile = AIProfile.from_json(clean)
        pid = profile.profile_id
        if not pid:
            pid = "prof_" + uuid.uuid4().hex[:8]
        validate_profile_id(pid)
        profile.profile_id = pid
        if not profile.name:
            profile.name = pid
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        profile.created_at = profile.created_at or now
        profile.updated_at = now
        problems = profile.validate()
        if problems:
            raise ValueError("；".join(problems))
        with self._lock:
            profiles = self._profiles_list()
            if any(p.get("profile_id") == pid for p in profiles):
                raise ValueError(f"profile 已存在: {pid}")
            profiles.append(_persistable(profile))
            if not self._config.get("default_profile_id"):
                self._config["default_profile_id"] = pid
            self._save_config()
        return profile

    def update_profile(self, profile_id: str, data: Dict[str, Any]) -> AIProfile:
        pid = validate_profile_id(profile_id)
        existing = self.get_profile(pid)
        if existing is None:
            raise KeyError(f"profile 不存在: {pid}")
        clean = {k: v for k, v in (data or {}).items() if k in ALLOWED_PROFILE_KEYS and k != "profile_id"}
        merged = AIProfile.from_json({**existing.to_json(), **clean})
        merged.profile_id = pid
        merged.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        problems = merged.validate()
        if problems:
            raise ValueError("；".join(problems))
        with self._lock:
            profiles = self._profiles_list()
            for i, p in enumerate(profiles):
                if p.get("profile_id") == pid:
                    profiles[i] = _persistable(merged)
                    break
            self._config.setdefault("capability_cache", {}).pop(pid, None)
            self._save_config()
        return merged

    def delete_profile(self, profile_id: str) -> None:
        pid = validate_profile_id(profile_id)
        with self._lock:
            profiles = self._profiles_list()
            before = len(profiles)
            self._config["profiles"] = [p for p in profiles if p.get("profile_id") != pid]
            if self._config.get("default_profile_id") == pid:
                self._config["default_profile_id"] = ""
            if before != len(self._config["profiles"]):
                self._secrets.delete(pid)
                self._config.get("capability_cache", {}).pop(pid, None)
                self._save_config()
            else:
                raise KeyError(f"profile 不存在: {pid}")

    # ---------- secrets 透传 ----------
    def set_api_key(self, profile_id: str, key: str) -> None:
        pid = validate_profile_id(profile_id)
        if not self.get_profile(pid):
            raise KeyError(f"profile 不存在: {pid}")
        self._secrets.set(pid, key)
        self.clear_capabilities(pid)

    def get_api_key(self, profile_id: str) -> Optional[str]:
        pid = validate_profile_id(profile_id)
        return self._secrets.get(pid)

    def masked_api_key(self, profile_id: str) -> str:
        try:
            return self._secrets.masked(validate_profile_id(profile_id))
        except ValueError:
            return ""

    def delete_api_key(self, profile_id: str) -> None:
        pid = validate_profile_id(profile_id)
        self._secrets.delete(pid)
        self.clear_capabilities(pid)

    # ---------- 能力缓存 ----------
    def get_capabilities(self, profile_id: str) -> Dict[str, Any]:
        cache = self._config.get("capability_cache", {})
        pid = validate_profile_id(profile_id)
        caps = dict(cache.get(pid, {}))
        profile = self.get_profile(pid)
        if not profile or caps.get("_profile_fingerprint") != _capability_fingerprint(profile):
            return {}
        caps.pop("_profile_fingerprint", None)
        return caps

    def set_capabilities(self, profile_id: str, caps: Dict[str, Any]) -> None:
        pid = validate_profile_id(profile_id)
        profile = self.get_profile(pid)
        if profile is None:
            raise KeyError(f"profile 不存在: {pid}")
        stored = dict(caps or {})
        stored["_profile_fingerprint"] = _capability_fingerprint(profile)
        with self._lock:
            self._config.setdefault("capability_cache", {})[pid] = stored
            self._save_config()

    def clear_capabilities(self, profile_id: str) -> None:
        pid = validate_profile_id(profile_id)
        with self._lock:
            self._config.setdefault("capability_cache", {}).pop(pid, None)
            self._save_config()

    # ---------- 请求日志（脱敏） ----------
    def append_request_log(self, entry: Dict[str, Any]) -> None:
        entry = {k: mask_key(v) if k in ("api_key", "detail_key") else v for k, v in entry.items()}
        entry.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))
        with self._lock:
            log = self._config.setdefault("request_log", [])
            log.append(entry)
            # 只保留最近 200 条
            self._config["request_log"] = log[-200:]
            self._save_config()

    def get_request_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        log = self._config.get("request_log", [])
        return list(log[-limit:])

    # ---------- 杂项设置 ----------
    def get_settings(self) -> Dict[str, Any]:
        return dict(self._config.get("settings", {}))

    def set_settings(self, settings: Dict[str, Any]) -> None:
        with self._lock:
            self._config["settings"] = settings
            self._save_config()


_STORE: Optional[ConfigStore] = None


def get_store() -> ConfigStore:
    global _STORE
    if _STORE is None:
        _STORE = ConfigStore()
    return _STORE


def reset_store_for_tests(base_dir: Path) -> ConfigStore:
    """测试用：重置单例并指向临时目录。"""
    global _STORE
    _STORE = ConfigStore(base_dir)
    return _STORE

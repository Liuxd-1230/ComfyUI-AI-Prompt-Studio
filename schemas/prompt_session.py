"""Versioned Prompt Studio session and immutable revision snapshots."""
import copy
import dataclasses
import hashlib
import time
import uuid
from typing import Any, ClassVar, Dict, List

from .base import Schema, SchemaError
from .prompt_plan import ValidationReport
from .results import ChatMessage

MAX_REVISIONS = 10
MAX_CONVERSATION_MESSAGES = 40


class _FrozenDict(dict):
    """JSON-compatible mapping that rejects every in-place mutation."""

    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("PromptRevision snapshot is immutable")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _immutable
    __ior__ = _immutable

    def __deepcopy__(self, memo: Dict[int, Any]) -> "_FrozenDict":
        return self


class _FrozenList(list):
    """JSON-compatible sequence that rejects every in-place mutation."""

    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("PromptRevision snapshot is immutable")

    __setitem__ = __delitem__ = append = clear = extend = insert = pop = remove = \
        reverse = sort = _immutable
    __iadd__ = __imul__ = _immutable

    def __deepcopy__(self, memo: Dict[int, Any]) -> "_FrozenList":
        return self


def _freeze_revision_value(value: Any) -> Any:
    if isinstance(value, Schema):
        value = value.to_json()
    if isinstance(value, dict):
        return _FrozenDict({key: _freeze_revision_value(item)
                            for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return _FrozenList(_freeze_revision_value(item) for item in value)
    return value


@dataclasses.dataclass
class SessionFingerprints(Schema):
    """Hashes that identify the target and authoritative context of a session."""

    target_signature: str = ""
    model_core_hash: str = ""
    source_hashes: Dict[str, str] = dataclasses.field(default_factory=dict)
    skill_hashes: Dict[str, str] = dataclasses.field(default_factory=dict)

    def mismatches(self, other: "SessionFingerprints") -> List[str]:
        mismatches: List[str] = []
        if (self.target_signature and other.target_signature
                and self.target_signature != other.target_signature):
            mismatches.append("target_signature")
        if (self.model_core_hash and other.model_core_hash
                and self.model_core_hash != other.model_core_hash):
            mismatches.append("model_core")
        keys = sorted(set(self.source_hashes) | set(other.source_hashes))
        mismatches.extend(
            f"source:{key}" for key in keys
            if self.source_hashes.get(key, "") != other.source_hashes.get(key, ""))
        keys = sorted(set(self.skill_hashes) | set(other.skill_hashes))
        mismatches.extend(
            f"skill:{key}" for key in keys
            if self.skill_hashes.get(key, "") != other.skill_hashes.get(key, ""))
        return mismatches


@dataclasses.dataclass
class PromptRevision(Schema):
    revision: int = 0
    revision_id: str = ""
    parent_revision: int = 0
    base_revision: int = 0
    plan: Dict[str, Any] = dataclasses.field(default_factory=dict)
    prompt: str = ""
    validation: Dict[str, Any] = dataclasses.field(default_factory=dict)
    user_instruction: str = ""
    change_summary: str = ""
    message_id: str = ""
    transaction_id: str = ""
    event_source: str = "user"
    repair_attempted: bool = False
    repair_count: int = 0
    requested_paths: List[str] = dataclasses.field(default_factory=list)
    dependent_paths: List[str] = dataclasses.field(default_factory=list)
    invalidated_paths: List[str] = dataclasses.field(default_factory=list)
    renderer_signature: str = ""
    model_core_hash: str = ""
    source_hashes: Dict[str, str] = dataclasses.field(default_factory=dict)
    skill_hashes: Dict[str, str] = dataclasses.field(default_factory=dict)
    timestamp: str = ""

    def __setattr__(self, name: str, value: Any) -> None:
        if self.__dict__.get("_sealed", False):
            raise AttributeError("PromptRevision snapshot is immutable")
        object.__setattr__(self, name, value)

    def __post_init__(self) -> None:
        if not self.revision_id:
            object.__setattr__(
                self, "revision_id", "prev_" + uuid.uuid4().hex[:16])
        if not self.timestamp:
            object.__setattr__(
                self, "timestamp", time.strftime("%Y-%m-%dT%H:%M:%S"))
        object.__setattr__(self, "repair_count", max(0, int(self.repair_count)))
        object.__setattr__(self, "repair_attempted", self.repair_count > 0)
        for name in ("plan", "validation", "requested_paths", "dependent_paths",
                     "invalidated_paths", "source_hashes", "skill_hashes"):
            object.__setattr__(
                self, name, _freeze_revision_value(getattr(self, name)))
        object.__setattr__(self, "_sealed", True)

    def __deepcopy__(self, memo: Dict[int, Any]) -> "PromptRevision":
        return self


def _migrate_session_v1_to_v2(data: Dict[str, Any]) -> Dict[str, Any]:
    """Preserve legacy workflow state while adding deterministic revision identity."""
    migrated = copy.deepcopy(data)
    session_id = str(migrated.get("id", "") or "psess_legacy")
    revisions = migrated.get("revisions", [])
    if isinstance(revisions, list):
        for index, raw in enumerate(revisions):
            if not isinstance(raw, dict):
                continue
            number = int(raw.get("revision", index + 1))
            raw.setdefault("revision_id", "prev_" + uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"ai-prompt-studio:{session_id}:revision:{number}").hex[:16])
            raw.setdefault("parent_revision", max(0, number - 1))
            raw.setdefault("base_revision", max(0, number - 1))
            raw.setdefault("event_source", "legacy")
    last_user_message = ""
    conversation = migrated.get("conversation", [])
    if isinstance(conversation, list):
        for item in reversed(conversation):
            if isinstance(item, dict) and item.get("role") == "user":
                last_user_message = str(item.get("content", "")).strip()
                break
    migrated.setdefault(
        "last_processed_message_id",
        ("legacy_" + hashlib.sha256(last_user_message.encode("utf-8")).hexdigest()[:20]
         if last_user_message else ""))
    migrated.setdefault("fingerprints", {})
    migrated.setdefault("fingerprint_state", "legacy_unbound")
    migrated["schema_version"] = "2.0"
    return migrated


@dataclasses.dataclass
class PromptSession(Schema):
    """Source of truth for one persistent CREATE/REFINE lifecycle."""

    CURRENT_SCHEMA_VERSION: ClassVar[str] = "2.0"
    MIGRATIONS: ClassVar[Dict[str, Dict[str, Any]]] = {
        "1.0": {"2.0": _migrate_session_v1_to_v2},
    }

    schema_version: str = "2.0"
    id: str = ""
    target_family: str = ""
    target_variant: str = ""
    current_plan: Dict[str, Any] = dataclasses.field(default_factory=dict)
    current_prompt: str = ""
    revision: int = 0
    conversation: List[ChatMessage] = dataclasses.field(default_factory=list)
    locked_constraints: List[str] = dataclasses.field(default_factory=list)
    validation: ValidationReport = dataclasses.field(default_factory=ValidationReport)
    revisions: List[PromptRevision] = dataclasses.field(default_factory=list)
    last_processed_message_id: str = ""
    fingerprints: SessionFingerprints = dataclasses.field(
        default_factory=SessionFingerprints)
    fingerprint_state: str = "bound"
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        for index, revision in enumerate(self.revisions):
            if not isinstance(revision, PromptRevision):
                raise SchemaError(
                    f"PromptSession.revisions[{index}] 必须是 PromptRevision")
        for index, message in enumerate(self.conversation):
            if not isinstance(message, ChatMessage):
                raise SchemaError(
                    f"PromptSession.conversation[{index}] 必须是 ChatMessage")
        if not isinstance(self.fingerprints, SessionFingerprints):
            raise SchemaError("PromptSession.fingerprints 必须是 SessionFingerprints")
        if self.fingerprint_state not in {"bound", "legacy_unbound"}:
            raise SchemaError("PromptSession.fingerprint_state 非法")
        if (self.has_current_plan
                and not (self.fingerprints.target_signature
                         or self.fingerprints.model_core_hash
                         or self.fingerprints.source_hashes
                         or self.fingerprints.skill_hashes)):
            self.fingerprint_state = "legacy_unbound"
        self.revisions = self.revisions[-MAX_REVISIONS:]
        self.conversation = self.conversation[-MAX_CONVERSATION_MESSAGES:]
        if not self.id:
            self.id = "psess_" + uuid.uuid4().hex[:12]
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    @classmethod
    def from_json(cls, data: Any) -> "PromptSession":
        candidate = data
        if isinstance(candidate, str):
            try:
                import json

                candidate = json.loads(candidate)
            except ValueError:
                candidate = None
        if isinstance(candidate, dict):
            version = str(candidate.get("schema_version", "1.0"))
            if version not in {"1.0", cls.CURRENT_SCHEMA_VERSION}:
                raise SchemaError(
                    f"PromptSession future schema_version {version!r} 无法安全编辑")
        restored = super().from_json(data)
        if not isinstance(restored, cls):
            raise SchemaError("PromptSession 反序列化结果类型错误")
        return restored

    @property
    def has_current_plan(self) -> bool:
        return bool(self.current_plan and self.current_prompt and self.revision > 0)

    def commit(self, plan: Dict[str, Any], prompt: str,
               validation: Dict[str, Any] | ValidationReport,
               user_instruction: str, change_summary: str, *,
               expected_revision: int | None = None,
               message_id: str = "",
               fingerprints: SessionFingerprints | Dict[str, Any] | None = None,
               parent_revision: int | None = None,
               event_source: str = "user",
               requested_paths: List[str] | None = None,
               dependent_paths: List[str] | None = None,
               invalidated_paths: List[str] | None = None,
               renderer_signature: str = "", repair_count: int = 0,
               transaction_id: str = "", node_instance_id: str = "",
               recovery_journal: Any = None) -> None:
        """Atomically commit a valid plan+prompt pair; invalid input changes nothing."""
        if expected_revision is not None and self.revision != expected_revision:
            raise ValueError(
                f"revision CAS 冲突：期望 {expected_revision}，当前 {self.revision}")
        if message_id and self.has_processed_message(message_id):
            raise ValueError(f"message nonce 已处理：{message_id}")
        report = ValidationReport.from_json(validation)
        if not report.valid:
            raise ValueError("validation 未通过，不能提交 PromptSession revision")
        if not isinstance(plan, dict) or not plan or not str(prompt or "").strip():
            raise ValueError("plan 与 prompt 必须是非空的有效结果")
        staged = copy.deepcopy(self)
        next_fingerprints = (SessionFingerprints.from_json(fingerprints)
                             if fingerprints is not None
                             else copy.deepcopy(staged.fingerprints))
        new_revision = staged.revision + 1
        transaction_id = transaction_id or "tx_" + uuid.uuid4().hex[:16]
        snapshot = PromptRevision(
            revision=new_revision,
            parent_revision=(staged.revision if parent_revision is None
                             else int(parent_revision)),
            base_revision=staged.revision,
            plan=copy.deepcopy(plan), prompt=str(prompt),
            validation=copy.deepcopy(report), user_instruction=user_instruction,
            change_summary=change_summary, message_id=message_id,
            transaction_id=transaction_id, event_source=event_source,
            repair_count=repair_count,
            requested_paths=list(requested_paths or []),
            dependent_paths=list(dependent_paths or []),
            invalidated_paths=list(invalidated_paths or []),
            renderer_signature=renderer_signature,
            model_core_hash=next_fingerprints.model_core_hash,
            source_hashes=copy.deepcopy(next_fingerprints.source_hashes),
            skill_hashes=copy.deepcopy(next_fingerprints.skill_hashes))
        staged.current_plan = copy.deepcopy(snapshot.plan)
        staged.current_prompt = snapshot.prompt
        staged.validation = copy.deepcopy(report)
        staged.revision = new_revision
        staged.revisions.append(snapshot)
        staged.revisions = staged.revisions[-MAX_REVISIONS:]
        staged.conversation.extend([
            ChatMessage(role="user", content=user_instruction),
            ChatMessage(role="assistant", content=change_summary),
        ])
        staged.conversation = staged.conversation[-MAX_CONVERSATION_MESSAGES:]
        staged.last_processed_message_id = message_id or staged.last_processed_message_id
        staged.fingerprints = next_fingerprints
        staged.fingerprint_state = "bound"
        staged.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        if recovery_journal is not None:
            from ..domain.recovery_journal import RecoveryJournalEntry

            recovery_journal.record_success(RecoveryJournalEntry(
                session_id=staged.id, node_instance_id=str(node_instance_id),
                transaction_id=transaction_id, base_revision=self.revision,
                result_revision=staged.revision,
                session_snapshot=staged.to_json()))
        # The stable object is swapped only after the complete next state exists.
        self.__dict__ = staged.__dict__

    def restore_revision(self, revision: int) -> bool:
        """Restore a historical snapshot by committing it as a new revision."""
        source = next((item for item in self.revisions
                       if item.revision == int(revision)), None)
        if source is None or source.revision == self.revision:
            return False
        self.commit(
            copy.deepcopy(source.plan), source.prompt,
            copy.deepcopy(source.validation), f"restore v{source.revision}",
            f"已恢复到 v{source.revision}，并创建新版本。",
            expected_revision=self.revision,
            message_id=f"restore:{source.revision}:{self.revision + 1}",
            parent_revision=source.revision, event_source="restore",
            renderer_signature=source.renderer_signature)
        return True

    def revert_previous(self) -> bool:
        """Legacy UI action: restore the preceding snapshot without deleting history."""
        if len(self.revisions) < 2:
            return False
        return self.restore_revision(self.revisions[-2].revision)

    def has_processed_message(self, message_id: str) -> bool:
        return bool(message_id and message_id == self.last_processed_message_id)

    def fingerprint_mismatches(
            self, fingerprints: SessionFingerprints | Dict[str, Any]) -> List[str]:
        if self.fingerprint_state == "legacy_unbound" and self.has_current_plan:
            return ["legacy_unbound"]
        return self.fingerprints.mismatches(
            SessionFingerprints.from_json(fingerprints))

    def reset(self, target_family: str = "", target_variant: str = "") -> None:
        fresh = PromptSession(target_family=target_family or self.target_family,
                              target_variant=target_variant or self.target_variant)
        for field in dataclasses.fields(self):
            if field.name != "schema_version":
                setattr(self, field.name, copy.deepcopy(getattr(fresh, field.name)))

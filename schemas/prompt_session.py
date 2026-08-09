"""Persistent domain state for iterative Prompt Studio and H3 Director work."""
import copy
import dataclasses
import time
import uuid
from typing import Any, Dict, List

from .base import Schema
from .prompt_plan import ValidationReport
from .results import ChatMessage


@dataclasses.dataclass
class PromptRevision(Schema):
    revision: int = 0
    plan: Dict[str, Any] = dataclasses.field(default_factory=dict)
    prompt: str = ""
    validation: ValidationReport = dataclasses.field(default_factory=ValidationReport)
    user_instruction: str = ""
    change_summary: str = ""
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")


@dataclasses.dataclass
class PromptSession(Schema):
    """Source of truth for one persistent CREATE/REFINE lifecycle."""

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
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        if not self.id:
            self.id = "psess_" + uuid.uuid4().hex[:12]
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    @property
    def has_current_plan(self) -> bool:
        return bool(self.current_plan and self.current_prompt and self.revision > 0)

    def commit(self, plan: Dict[str, Any], prompt: str,
               validation: Dict[str, Any] | ValidationReport,
               user_instruction: str, change_summary: str, *,
               expected_revision: int | None = None) -> None:
        """Atomically commit a valid plan+prompt pair; invalid input changes nothing."""
        if expected_revision is not None and self.revision != expected_revision:
            raise ValueError(
                f"revision CAS 冲突：期望 {expected_revision}，当前 {self.revision}")
        report = ValidationReport.from_json(validation)
        if not report.valid:
            raise ValueError("validation 未通过，不能提交 PromptSession revision")
        if not isinstance(plan, dict) or not plan or not str(prompt or "").strip():
            raise ValueError("plan 与 prompt 必须是非空的有效结果")
        staged = copy.deepcopy(self)
        new_revision = staged.revision + 1
        snapshot = PromptRevision(
            revision=new_revision, plan=copy.deepcopy(plan), prompt=str(prompt),
            validation=copy.deepcopy(report), user_instruction=user_instruction,
            change_summary=change_summary)
        staged.current_plan = copy.deepcopy(snapshot.plan)
        staged.current_prompt = snapshot.prompt
        staged.validation = copy.deepcopy(report)
        staged.revision = new_revision
        staged.revisions.append(snapshot)
        staged.revisions = staged.revisions[-5:]
        staged.conversation.extend([
            ChatMessage(role="user", content=user_instruction),
            ChatMessage(role="assistant", content=change_summary),
        ])
        staged.conversation = staged.conversation[-20:]
        staged.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        # The stable object is swapped only after the complete next state exists.
        self.__dict__ = staged.__dict__

    def revert_previous(self) -> bool:
        if len(self.revisions) < 2:
            return False
        self.revisions.pop()
        previous = self.revisions[-1]
        self.current_plan = copy.deepcopy(previous.plan)
        self.current_prompt = previous.prompt
        self.validation = copy.deepcopy(previous.validation)
        self.revision = previous.revision
        self.conversation.append(ChatMessage(
            role="assistant", content=f"已恢复到 v{self.revision}。"))
        self.conversation = self.conversation[-20:]
        self.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        return True

    def reset(self, target_family: str = "", target_variant: str = "") -> None:
        fresh = PromptSession(target_family=target_family or self.target_family,
                              target_variant=target_variant or self.target_variant)
        for field in dataclasses.fields(self):
            if field.name != "schema_version":
                setattr(self, field.name, copy.deepcopy(getattr(fresh, field.name)))

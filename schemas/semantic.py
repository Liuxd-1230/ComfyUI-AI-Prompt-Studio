"""Semantic consistency, risk, and bounded-repair result schemas."""
import dataclasses
from typing import Any

from .base import Schema


@dataclasses.dataclass
class SemanticIssue(Schema):
    severity: str = "error"       # error | warning | info
    code: str = ""
    path: str = ""
    message: str = ""
    reason: str = ""
    evidence: list[str] = dataclasses.field(default_factory=list)
    repairable: bool = False


@dataclasses.dataclass
class RiskAssessment(Schema):
    level: str = "low"            # low | medium | high
    score: int = 0
    reasons: list[str] = dataclasses.field(default_factory=list)
    critic_required: bool = False


@dataclasses.dataclass
class ConsistencyResult(Schema):
    plan: dict[str, Any] = dataclasses.field(default_factory=dict)
    issues: list[SemanticIssue] = dataclasses.field(default_factory=list)
    risk: RiskAssessment = dataclasses.field(default_factory=RiskAssessment)
    critic_invoked: bool = False
    repair_attempted: bool = False
    repair_count: int = 0

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

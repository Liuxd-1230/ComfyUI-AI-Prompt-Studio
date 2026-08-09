"""Target-family adapters for typed semantic plans."""
from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from typing import Any, Generic, TypeVar

from ..schemas.anima import AnimaPromptPlan
from ..schemas.h3 import H3PromptPlan


PlanT = TypeVar("PlanT")


class PlanAdapter(ABC, Generic[PlanT]):
    """Boundary used by transactions instead of family conditionals."""

    family: str
    plan_type: type[PlanT]

    @abstractmethod
    def load(self, payload: Any) -> PlanT:
        raise NotImplementedError

    @abstractmethod
    def normalize(self, plan: PlanT) -> PlanT:
        raise NotImplementedError

    @abstractmethod
    def to_llm_context(self, plan: PlanT) -> dict[str, Any]:
        raise NotImplementedError

    def llm_context(self, plan: PlanT) -> dict[str, Any]:
        """Compatibility alias for the short-lived P1 pre-release API."""
        return self.to_llm_context(plan)

    def clone(self, plan: PlanT) -> PlanT:
        return deepcopy(plan)


class AnimaPlanAdapter(PlanAdapter[AnimaPromptPlan]):
    family = "anima"
    plan_type = AnimaPromptPlan

    def load(self, payload: Any) -> AnimaPromptPlan:
        return AnimaPromptPlan.from_json(payload)

    def normalize(self, plan: AnimaPromptPlan) -> AnimaPromptPlan:
        return plan.normalized()

    def to_llm_context(self, plan: AnimaPromptPlan) -> dict[str, Any]:
        return plan.to_llm_context()


class H3PlanAdapter(PlanAdapter[H3PromptPlan]):
    family = "minimax_h3"
    plan_type = H3PromptPlan

    def load(self, payload: Any) -> H3PromptPlan:
        return H3PromptPlan.from_json(payload)

    def normalize(self, plan: H3PromptPlan) -> H3PromptPlan:
        clone = self.clone(plan)
        clone.shots.sort(key=lambda shot: shot.index)
        clone.speakers.sort(key=lambda speaker: speaker.speaker_id)
        return clone

    def to_llm_context(self, plan: H3PromptPlan) -> dict[str, Any]:
        return plan.to_llm_context()


_ADAPTERS: dict[str, PlanAdapter[Any]] = {
    AnimaPlanAdapter.family: AnimaPlanAdapter(),
    H3PlanAdapter.family: H3PlanAdapter(),
}


def get_plan_adapter(family: str) -> PlanAdapter[Any]:
    try:
        return _ADAPTERS[family]
    except KeyError as exc:
        raise ValueError(f"没有注册语义计划适配器: {family!r}") from exc

"""Target-family adapters for typed semantic plans."""
from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from typing import Any, Generic, TypeVar

from ..schemas.anima import AnimaPromptPlan
from ..schemas.h3 import H3PromptPlan
from ..schemas.text_prompt import TextPromptPlan
from ..schemas.image_semantic_plan import ImageSemanticPlan


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

    def clone(self, plan: PlanT) -> PlanT:
        return deepcopy(plan)

    def dump(self, plan: PlanT) -> dict[str, Any]:
        return plan.to_json()  # type: ignore[attr-defined]


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
        # A list delete/insert changes positional semantics. Reassign the
        # public H3 shot numbers after sorting so the renderer and validator
        # cannot emit a gap such as Shot 1 / Shot 3 after deleting Shot 2.
        for index, shot in enumerate(clone.shots, start=1):
            shot.index = index
        clone.speakers.sort(key=lambda speaker: speaker.speaker_id)
        return clone

    def to_llm_context(self, plan: H3PromptPlan) -> dict[str, Any]:
        return plan.to_llm_context()


class TextPromptPlanAdapter(PlanAdapter[TextPromptPlan]):
    """Typed adapter for Z-Image, Qwen Image Edit and generic prose plans."""

    plan_type = TextPromptPlan

    def __init__(self, family: str) -> None:
        self.family = family

    def load(self, payload: Any) -> TextPromptPlan:
        return TextPromptPlan.from_json(payload)

    def normalize(self, plan: TextPromptPlan) -> TextPromptPlan:
        return self.clone(plan)

    def to_llm_context(self, plan: TextPromptPlan) -> dict[str, Any]:
        return plan.to_llm_context()


class ImageSemanticPlanAdapter(PlanAdapter[ImageSemanticPlan]):
    """Session adapter that keeps positive content and negative text together."""

    plan_type = ImageSemanticPlan

    def __init__(self, family: str) -> None:
        self.family = family
        self.content_adapter = get_plan_adapter(family)

    def load(self, payload: Any) -> ImageSemanticPlan:
        plan = ImageSemanticPlan.from_json(payload)
        content = self.content_adapter.load(plan.content)
        plan.content = self.content_adapter.dump(content)
        return plan

    def normalize(self, plan: ImageSemanticPlan) -> ImageSemanticPlan:
        clone = self.clone(plan)
        content = self.content_adapter.load(clone.content)
        clone.content = self.content_adapter.dump(
            self.content_adapter.normalize(content))
        clone.negative = clone.negative.strip()
        return clone

    def to_llm_context(self, plan: ImageSemanticPlan) -> dict[str, Any]:
        content = self.content_adapter.load(plan.content)
        return {"content": self.content_adapter.to_llm_context(content),
                "negative": plan.negative}


_ADAPTERS: dict[str, PlanAdapter[Any]] = {
    AnimaPlanAdapter.family: AnimaPlanAdapter(),
    H3PlanAdapter.family: H3PlanAdapter(),
}
_TEXT_PLAN_FAMILIES = {
    "z_image", "qwen_image_edit", "generic_image", "sdxl", "flux",
}


def get_plan_adapter(family: str) -> PlanAdapter[Any]:
    if family in _ADAPTERS:
        return _ADAPTERS[family]
    if family in _TEXT_PLAN_FAMILIES:
        return TextPromptPlanAdapter(family)
    raise ValueError(f"没有注册语义计划适配器: {family!r}")


def get_session_plan_adapter(family: str) -> PlanAdapter[Any]:
    if family == "minimax_h3":
        return get_plan_adapter(family)
    return ImageSemanticPlanAdapter(family)

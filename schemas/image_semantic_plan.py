"""Editable semantic state shared by all image-prompt families."""
import dataclasses
from typing import Any

from .base import Schema


@dataclasses.dataclass
class ImageSemanticPlan(Schema):
    """Positive-plan content and negative constraints form one impact graph."""

    content: dict[str, Any] = dataclasses.field(default_factory=dict)
    negative: str = ""

"""Formal ANIMA semantic plan schemas.

The renderer consumes these types but does not own them.  ``natural_body`` is
the residual scene description; character identity/action/position facts belong
to ``characters`` and must not be copied into it by new producers.
"""
import dataclasses
from typing import Any

from .base import Schema


ANIMA_NORMAL_FORM_VERSION = "1.0"


@dataclasses.dataclass
class AnimaCharacter(Schema):
    """One subject binding with stable and variable facts kept separate."""

    character_id: str = ""
    name: str = ""
    required_traits: list[str] = dataclasses.field(default_factory=list)
    variable_traits: list[str] = dataclasses.field(default_factory=list)
    action: str = ""
    position: str = ""
    description: str = ""  # legacy fallback; new plans use the fields above

    def normalized(self) -> "AnimaCharacter":
        return AnimaCharacter(
            character_id=self.character_id.strip(),
            name=self.name.strip(),
            required_traits=_dedupe(self.required_traits),
            variable_traits=_dedupe(self.variable_traits),
            action=self.action.strip(),
            position=self.position.strip(),
            description=self.description.strip(),
        )


@dataclasses.dataclass
class AnimaPromptPlan(Schema):
    """ANIMA Plan Normal Form shared by adapters, renderers, and validators."""

    normal_form_version: str = ANIMA_NORMAL_FORM_VERSION
    natural_body: str = ""
    characters: list[AnimaCharacter] = dataclasses.field(default_factory=list)
    control_tags: list[str] = dataclasses.field(default_factory=list)
    character_tags: list[str] = dataclasses.field(default_factory=list)
    series_tags: list[str] = dataclasses.field(default_factory=list)
    artist_tags: list[str] = dataclasses.field(default_factory=list)
    visual_tags: list[str] = dataclasses.field(default_factory=list)
    style: list[str] = dataclasses.field(default_factory=list)
    environment: list[str] = dataclasses.field(default_factory=list)
    composition: str = ""
    lighting: str = ""
    negative_constraints: list[str] = dataclasses.field(default_factory=list)

    def normalized(self) -> "AnimaPromptPlan":
        """Return a deterministic copy suitable for comparison and rendering."""
        return AnimaPromptPlan(
            natural_body=self.natural_body.strip(),
            characters=[c.normalized() for c in self.characters],
            control_tags=_dedupe(self.control_tags),
            character_tags=_dedupe(self.character_tags),
            series_tags=_dedupe(self.series_tags),
            artist_tags=_dedupe(self.artist_tags),
            visual_tags=_dedupe(self.visual_tags),
            style=_dedupe(self.style),
            environment=_dedupe(self.environment),
            composition=self.composition.strip(),
            lighting=self.lighting.strip(),
            negative_constraints=_dedupe(self.negative_constraints),
        )

    def to_llm_context(self) -> dict[str, Any]:
        """Compact semantic context without renderer or execution metadata."""
        data = self.normalized().to_json()
        data.pop("schema_version", None)
        data.pop("normal_form_version", None)
        return _drop_empty(data)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        clean = str(value).strip()
        if clean and clean not in result:
            result.append(clean)
    return result


def _drop_empty(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: cleaned for key, item in value.items()
                if key != "schema_version"
                if (cleaned := _drop_empty(item)) not in (None, "", [], {})}
    if isinstance(value, list):
        return [cleaned for item in value
                if (cleaned := _drop_empty(item)) not in (None, "", [], {})]
    return value

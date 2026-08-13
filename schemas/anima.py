"""Formal ANIMA semantic plan schemas with one owner per semantic fact."""
import dataclasses
import re
from typing import Any
from .base import Schema, SchemaError


ANIMA_NORMAL_FORM_VERSION = "2.0"


@dataclasses.dataclass
class AnimaCharacter(Schema):
    """One subject binding with stable and variable facts kept separate."""

    character_id: str = ""
    name: str = ""
    required_traits: list[str] = dataclasses.field(default_factory=list)
    variable_traits: list[str] = dataclasses.field(default_factory=list)
    action: str = ""
    position: str = ""
    creative_notes: list[str] = dataclasses.field(default_factory=list)

    def normalized(self) -> "AnimaCharacter":
        return AnimaCharacter(
            character_id=self.character_id.strip(),
            name=self.name.strip(),
            required_traits=_dedupe(self.required_traits),
            variable_traits=_dedupe(self.variable_traits),
            action=self.action.strip(),
            position=self.position.strip(),
            creative_notes=_dedupe(self.creative_notes),
        )


@dataclasses.dataclass
class AnimaPromptPlan(Schema):
    """ANIMA Plan Normal Form shared by adapters, renderers, and validators."""

    normal_form_version: str = ANIMA_NORMAL_FORM_VERSION
    scene_description: str = ""
    creative_notes: list[str] = dataclasses.field(default_factory=list)
    characters: list[AnimaCharacter] = dataclasses.field(default_factory=list)
    control_tags: list[str] = dataclasses.field(default_factory=list)
    series_tags: list[str] = dataclasses.field(default_factory=list)
    artist_tags: list[str] = dataclasses.field(default_factory=list)
    supplemental_tags: list[str] = dataclasses.field(default_factory=list)
    style: list[str] = dataclasses.field(default_factory=list)
    environment: list[str] = dataclasses.field(default_factory=list)
    composition: str = ""
    lighting: str = ""
    negative_constraints: list[str] = dataclasses.field(default_factory=list)

    @classmethod
    def from_json(cls, data: Any) -> "AnimaPromptPlan":
        """Load only the current Plan Normal Form."""
        if isinstance(data, cls):
            if data.normal_form_version == ANIMA_NORMAL_FORM_VERSION:
                return data
            data = data.to_json()
        if isinstance(data, str):
            import json

            try:
                parsed = json.loads(data)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                data = parsed
        if isinstance(data, dict):
            version = str(data.get("normal_form_version", "") or "")
            if version != ANIMA_NORMAL_FORM_VERSION:
                raise SchemaError(
                    "AnimaPromptPlan 仅支持 normal_form_version '2.0'；"
                    f"收到 {version!r}")
            data = dict(data)
            for field_name in (
                    "creative_notes", "characters", "control_tags", "series_tags",
                    "artist_tags", "supplemental_tags", "style", "environment",
                    "negative_constraints"):
                value = data.get(field_name, [])
                if value is not None and not isinstance(value, (list, tuple)):
                    raise SchemaError(
                        f"AnimaPromptPlan.{field_name} 必须是数组，实际是 "
                        f"{type(value).__name__}")
        loaded = super().from_json(data)
        if not isinstance(loaded, cls):  # defensive typing boundary
            raise TypeError("AnimaPromptPlan migration returned an unexpected type")
        if any(not isinstance(character, AnimaCharacter)
               for character in loaded.characters):
            raise SchemaError("AnimaPromptPlan.characters 必须只包含人物对象")
        return loaded

    def normalized(self) -> "AnimaPromptPlan":
        """Return a deterministic copy suitable for comparison and rendering."""
        return AnimaPromptPlan(
            normal_form_version=ANIMA_NORMAL_FORM_VERSION,
            scene_description=self.scene_description.strip(),
            creative_notes=_dedupe(self.creative_notes),
            characters=[_normalized_character(c) for c in self.characters],
            control_tags=_dedupe(self.control_tags),
            series_tags=_dedupe(self.series_tags),
            artist_tags=_dedupe(self.artist_tags),
            supplemental_tags=_dedupe(self.supplemental_tags),
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

    def validate(self) -> list[str]:
        """Reject overlaps across the complete editable-owner matrix."""
        facts = _ownership_facts(self)
        issues: list[str] = []
        for left_index, left in enumerate(facts):
            for right in facts[left_index + 1:]:
                if _facts_overlap(left, right):
                    issues.append(
                        f"{right.path}: {right.value!r} 与 {left.path} 重复；"
                        "同一事实只能有一个 editable owner")
        return issues


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        clean = str(value).strip()
        if clean and clean not in result:
            result.append(clean)
    return result


def _normalized_character(value: Any) -> AnimaCharacter:
    if not isinstance(value, AnimaCharacter):
        raise SchemaError("AnimaPromptPlan.characters 必须只包含人物对象")
    return value.normalized()


@dataclasses.dataclass(frozen=True)
class _OwnershipFact:
    path: str
    value: str
    prose: bool = False
    scope: str = ""


def _ownership_facts(plan: AnimaPromptPlan) -> list[_OwnershipFact]:
    facts: list[_OwnershipFact] = []
    if plan.scene_description.strip():
        facts.append(_OwnershipFact("scene_description", plan.scene_description, True))
    facts.extend(_OwnershipFact(f"creative_notes/{index}", value, True)
                 for index, value in enumerate(plan.creative_notes) if value.strip())
    for char_index, character in enumerate(plan.characters):
        base = f"characters/{char_index}"
        scope = f"character:{char_index}"
        facts.extend(_OwnershipFact(f"{base}/required_traits/{index}", value,
                                    scope=scope)
                     for index, value in enumerate(character.required_traits)
                     if value.strip())
        facts.extend(_OwnershipFact(f"{base}/variable_traits/{index}", value,
                                    scope=scope)
                     for index, value in enumerate(character.variable_traits)
                     if value.strip())
        if character.action.strip():
            facts.append(_OwnershipFact(f"{base}/action", character.action,
                                        scope=scope))
        if character.position.strip():
            facts.append(_OwnershipFact(f"{base}/position", character.position,
                                        scope=scope))
        facts.extend(_OwnershipFact(f"{base}/creative_notes/{index}", value,
                                    True, scope)
                     for index, value in enumerate(character.creative_notes)
                     if value.strip())
    for group_name, values in (
            ("environment", plan.environment), ("style", plan.style),
            ("control_tags", plan.control_tags), ("series_tags", plan.series_tags),
            ("artist_tags", plan.artist_tags),
            ("supplemental_tags", plan.supplemental_tags)):
        facts.extend(_OwnershipFact(f"{group_name}/{index}", value)
                     for index, value in enumerate(values) if value.strip())
    if plan.composition.strip():
        facts.append(_OwnershipFact("composition", plan.composition, True))
    if plan.lighting.strip():
        facts.append(_OwnershipFact("lighting", plan.lighting, True))
    return facts


def _facts_overlap(left: _OwnershipFact, right: _OwnershipFact) -> bool:
    if left.scope and right.scope and left.scope != right.scope:
        return False
    if left.value.strip().casefold() == right.value.strip().casefold():
        return True
    if left.prose and _fragment_in_text(left.value, right.value):
        return True
    if right.prose and _fragment_in_text(right.value, left.value):
        return True
    return False


def _drop_empty(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: cleaned for key, item in value.items()
                if key != "schema_version"
                if (cleaned := _drop_empty(item)) not in (None, "", [], {})}
    if isinstance(value, list):
        return [cleaned for item in value
                if (cleaned := _drop_empty(item)) not in (None, "", [], {})]
    return value


def _fragment_in_text(text: str, fragment: str) -> bool:
    clean = fragment.strip()
    if not clean or not text.strip():
        return False
    return re.search(r"(?<!\w)" + re.escape(clean) + r"(?!\w)", text,
                     flags=re.IGNORECASE) is not None

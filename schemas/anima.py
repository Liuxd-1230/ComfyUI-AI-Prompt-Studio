"""Formal ANIMA semantic plan schemas.

Version 2 is the Plan Normal Form: character facts live only on character
records, while ``scene_description`` is reserved for non-character scene prose.
Legacy prose fields are migrated at the schema boundary and never survive as a
second editable truth source.
"""
import dataclasses
import re
from typing import Any, Callable

from .base import Schema, SchemaError


ANIMA_NORMAL_FORM_VERSION = "2.0"


class AnimaMigrationConflict(SchemaError):
    """Legacy prose overlaps structured facts and cannot be split losslessly."""


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
        """Load current or v1 plans through the explicit normal-form migration."""
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
            data = _migrate_normal_form(dict(data))
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


def _migrate_normal_form(data: dict[str, Any]) -> dict[str, Any]:
    """Run registered migrations until the current normal-form version."""
    version = str(data.get("normal_form_version", "1.0") or "1.0")
    visited: set[str] = set()
    while version != ANIMA_NORMAL_FORM_VERSION:
        if version in visited or version not in ANIMA_NORMAL_FORM_MIGRATIONS:
            raise ValueError(f"不支持的 ANIMA Plan Normal Form 版本: {version}")
        visited.add(version)
        target, migrate = ANIMA_NORMAL_FORM_MIGRATIONS[version]
        data = migrate(dict(data))
        version = target
        data["normal_form_version"] = version
    return data


def _migrate_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """Remove v1 prose caches while retaining their only non-duplicated facts."""
    legacy_body = str(data.get("natural_body", "") or "").strip()
    retained_scene = [*_legacy_list(data.get("environment")),
                      *_legacy_list(data.get("style")),
                      *_legacy_list(data.get("control_tags")),
                      *_legacy_list(data.get("series_tags")),
                      *_legacy_list(data.get("artist_tags")),
                      *_legacy_list(data.get("character_tags")),
                      *_legacy_list(data.get("visual_tags")),
                      *_legacy_list(data.get("supplemental_tags")),
                      *_legacy_list(data.get("creative_notes")),
                      data.get("scene_description", ""),
                      data.get("composition", ""), data.get("lighting", "")]
    retained_character_facts = [
        value
        for raw in data.get("characters") or [] if isinstance(raw, dict)
        for value in [*_legacy_list(raw.get("required_traits")),
                      *_legacy_list(raw.get("variable_traits")),
                      *_legacy_list(raw.get("creative_notes")),
                      raw.get("action", ""), raw.get("position", ""),
                      raw.get("description", "")]
    ]
    if legacy_body and any(str(value or "").strip()
                           for value in [*retained_scene, *retained_character_facts]):
        raise AnimaMigrationConflict(
            "ANIMA v1 natural_body 是未分类完整 prose，且与其他语义字段并存，"
            "无法证明事实所有权并无损自动迁移；"
            "上一版会话保持不变，请新建会话或先移除重复 prose")

    data.pop("natural_body", None)
    if legacy_body:
        notes = _legacy_list(data.get("creative_notes"))
        notes.append(legacy_body)
        data["creative_notes"] = notes
    data.setdefault("scene_description", "")
    migrated_characters: list[dict[str, Any]] = []
    for raw in data.get("characters") or []:
        if not isinstance(raw, dict):
            raise SchemaError("ANIMA v1 characters 必须只包含人物对象")
        character = dict(raw)
        legacy_description = str(character.pop("description", "") or "").strip()
        has_structured_facts = bool(
            character.get("required_traits") or character.get("variable_traits") or
            character.get("action") or character.get("position") or
            character.get("creative_notes"))
        if legacy_description and not has_structured_facts:
            notes = _legacy_list(character.get("creative_notes"))
            notes.append(legacy_description)
            character["creative_notes"] = notes
        elif legacy_description:
            raise AnimaMigrationConflict(
                "ANIMA v1 character.description 与结构化人物字段并存，"
                "无法判断独有事实；上一版会话保持不变，请新建会话或先整理旧计划")
        migrated_characters.append(character)
    data["characters"] = migrated_characters
    legacy_tags = [*_legacy_list(data.pop("character_tags", [])),
                   *_legacy_list(data.pop("visual_tags", [])),
                   *_legacy_list(data.get("supplemental_tags", []))]
    data["supplemental_tags"] = _dedupe(legacy_tags)
    return data


ANIMA_NORMAL_FORM_MIGRATIONS: dict[
    str, tuple[str, Callable[[dict[str, Any]], dict[str, Any]]]
] = {"1.0": ("2.0", _migrate_v1_to_v2)}


def _legacy_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]

"""人物特征：CharacterTrait / CharacterCandidate / CharacterBible。"""


import dataclasses
import time
from typing import List, Optional

from .base import Schema

# 特征类别（规范要求必须区分）
TRAIT_CATEGORIES = ["stable", "variable", "current", "uncertain"]

MERGE_STRATEGIES = ["manual_priority", "text_priority", "image_priority", "consensus", "fill_missing_only"]


@dataclasses.dataclass
class CharacterTrait(Schema):
    """单个人物特征，带类别/置信度/来源证据/锁定状态。"""

    name: str = ""                  # 例如 hair_color
    value: str = ""                 # 例如 long dark brown hair
    category: str = "stable"        # stable | variable | current | uncertain
    confidence: float = 0.5         # 0-1
    sources: List[str] = dataclasses.field(default_factory=list)   # 来源证据（文字锚点/图片引用/档案）
    locked: bool = False            # 人工锁定，合并时不可被覆盖

    def validate(self) -> list[str]:
        problems = []
        if not self.name:
            problems.append("CharacterTrait: name 不能为空")
        if self.category not in TRAIT_CATEGORIES:
            problems.append(f"CharacterTrait: 非法类别 {self.category!r}")
        return problems


@dataclasses.dataclass
class CharacterConflict(Schema):
    """多来源特征冲突。"""

    trait_name: str = ""
    values: List[str] = dataclasses.field(default_factory=list)
    reason: str = ""
    resolution_hint: str = ""


@dataclasses.dataclass
class CharacterCandidate(Schema):
    """单次分析（单图/单段文字）产出的人物特征推断。"""

    candidate_id: str = ""
    name: str = ""
    traits: List[CharacterTrait] = dataclasses.field(default_factory=list)
    analysis_mode: str = "character_full"
    sources: List[str] = dataclasses.field(default_factory=list)   # 资产引用或文字锚点
    confidence: float = 0.5
    raw: str = ""                   # 模型原始输出
    created_at: str = ""

    def __post_init__(self):
        import uuid

        if not self.candidate_id:
            self.candidate_id = "cand_" + uuid.uuid4().hex[:10]
        if not self.created_at:
            self.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")


@dataclasses.dataclass
class CharacterBible(Schema):
    """人物稳定身份总和：特征 + 锁定字段 + 冲突 + 来源追踪 + 不确定性。"""

    character_id: str = ""
    name: str = ""
    speaker_id: str = ""            # H3 说话人 ID（S1/S2...），自动分配
    traits: List[CharacterTrait] = dataclasses.field(default_factory=list)
    locked_fields: List[str] = dataclasses.field(default_factory=list)   # 锁定的特征名
    conflicts: List[CharacterConflict] = dataclasses.field(default_factory=list)
    sources: List[str] = dataclasses.field(default_factory=list)
    uncertainty_notes: List[str] = dataclasses.field(default_factory=list)
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        import uuid

        if not self.character_id:
            self.character_id = "char_" + uuid.uuid4().hex[:8]
        if not self.speaker_id:
            self.speaker_id = "S1"
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def touch(self) -> None:
        self.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    def trait_map(self) -> dict:
        return {t.name: t for t in self.traits}

    def locked_traits(self) -> List[CharacterTrait]:
        return [t for t in self.traits if t.locked or t.name in self.locked_fields]

    def uncertain_traits(self) -> List[CharacterTrait]:
        return [t for t in self.traits if t.category == "uncertain"]

    def stable_traits(self) -> List[CharacterTrait]:
        return [t for t in self.traits if t.category == "stable"]

    def character_prompt(self, language: str = "en") -> str:
        """渲染为供 ANIMA/Composer 使用的人物提示片段（如 "young woman, long dark hair"）。"""
        parts = []
        if self.name:
            parts.append(self.name)
        for t in self.traits:
            if t.category == "uncertain":
                continue
            if t.value and t.value not in parts:
                parts.append(t.value)
        return ", ".join(parts)

    def conflict_report_text(self) -> str:
        if not self.conflicts:
            return ""
        lines = []
        for c in self.conflicts:
            lines.append(f"- {c.trait_name}: {(' vs '.join(c.values))} — {c.reason}")
        return "\n".join(lines)

    def uncertainty_text(self) -> str:
        if not self.uncertainty_notes:
            return ""
        return "\n".join(f"- {n}" for n in self.uncertainty_notes)


@dataclasses.dataclass
class CharacterBook(Schema):
    """多个 CharacterBible 的容器（同一工作流多人物场景）。"""

    characters: List[CharacterBible] = dataclasses.field(default_factory=list)
    default_character_id: str = ""

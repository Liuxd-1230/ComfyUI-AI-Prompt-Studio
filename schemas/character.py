"""人物特征：CharacterTrait / CharacterCandidate / CharacterBible。"""


import dataclasses
import re
import time
from typing import List, Optional

from .base import Schema

# 特征类别（规范要求必须区分）
TRAIT_CATEGORIES = ["stable", "variable", "current", "uncertain"]

MERGE_STRATEGIES = ["manual_priority", "text_priority", "image_priority", "consensus", "fill_missing_only"]

_SPEAKER_ID_RE = re.compile(r"S\d+")


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
    conflicts: List[CharacterConflict] = dataclasses.field(default_factory=list)
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
        # 注意：speaker_id 不在这里默认成 S1（曾导致所有人物撞号）。
        # 唯一 Speaker ID 由 CharacterBook.assign_speaker_ids() 统一分配。
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
    """多个 CharacterBible 的容器（同一工作流多人物场景）。

    职责（docs/decisions.md D17）：
    - 按 character_id 去重（同一人物只存一份）；
    - 统一分配唯一 Speaker ID（char_01→S1, char_02→S2...）；
    - 已存在 Speaker ID 保持稳定；删除人物不改动他人 ID；
      新人物取下一个可用 ID；冲突修复并记 warning。
    """

    characters: List[CharacterBible] = dataclasses.field(default_factory=list)
    default_character_id: str = ""

    def get_character(self, character_id: str) -> Optional[CharacterBible]:
        for c in self.characters:
            if c.character_id == character_id:
                return c
        return None

    def find_by_name(self, name: str) -> Optional[CharacterBible]:
        """按人物名查找（更新路径：同名人物复用其 character_id 与 Speaker ID）。"""
        for c in self.characters:
            if c.name and c.name == name:
                return c
        return None

    def speaker_id_for(self, character_id: str) -> str:
        c = self.get_character(character_id)
        return (c.speaker_id or "") if c else ""

    def used_speaker_ids(self) -> List[str]:
        seen = []
        for c in self.characters:
            sid = (c.speaker_id or "").strip()
            if sid and sid not in seen:
                seen.append(sid)
        return seen

    def next_free_speaker_id_for(self, used: dict) -> str:
        i = 1
        while f"S{i}" in used:
            i += 1
        return f"S{i}"

    def assign_speaker_ids(self) -> List[str]:
        """统一分配唯一 Speaker ID（保持稳定；冲突修复）。返回 warning 列表。"""
        warnings: List[str] = []
        used: dict = {}  # speaker_id -> character_id
        for c in self.characters:
            sid = (c.speaker_id or "").strip()
            if not sid or not _SPEAKER_ID_RE.fullmatch(sid):
                if sid:
                    warnings.append(
                        f"{c.character_id}: Speaker ID {sid!r} 非法，已改为自动分配")
                c.speaker_id = self.next_free_speaker_id_for(used)
                used[c.speaker_id] = c.character_id
            elif sid in used:
                fixed = self.next_free_speaker_id_for(used)
                warnings.append(
                    f"{c.character_id}: Speaker ID {sid} 与 {used[sid]} 冲突，已改为 {fixed}")
                c.speaker_id = fixed
                used[c.speaker_id] = c.character_id
            else:
                used[c.speaker_id] = c.character_id
        return warnings

    def upsert_character(self, bible: CharacterBible) -> List[str]:
        """按 character_id 添加或更新人物（不重复添加）。返回 warning 列表。"""
        warnings: List[str] = []
        if not bible.character_id:
            raise ValueError("CharacterBible 缺少 character_id，无法加入 CharacterBook")
        existing = self.get_character(bible.character_id)
        if existing is not None:
            # 更新：保留已分配的 Speaker ID（稳定），其余以新档案为准
            if existing.speaker_id and not bible.speaker_id:
                bible.speaker_id = existing.speaker_id
            self.characters = [c for c in self.characters
                               if c.character_id != bible.character_id]
        self.characters.append(bible)
        return warnings

    def first_bible(self) -> Optional[CharacterBible]:
        """兼容视图：取默认或第一个档案（单人物工作流）。"""
        c = self.get_character(self.default_character_id) or (
            self.characters[0] if self.characters else None)
        return c

    def to_payload(self) -> dict:
        return self.to_json()

    @classmethod
    def from_bible(cls, bible: CharacterBible) -> "CharacterBook":
        book = CharacterBook()
        if bible and bible.character_id:
            book.characters.append(bible)
            book.default_character_id = bible.character_id
        return book

    def context_text(self) -> str:
        """供 LLM 提示词使用的紧凑角色表（含 Speaker ID 与稳定特征）。"""
        lines = []
        for c in self.characters:
            stable = [t.value for t in c.stable_traits() if t.value]
            sid = c.speaker_id or self.speaker_id_for(c.character_id) or "?"
            name = c.name or c.character_id
            if stable:
                lines.append(f"{c.character_id} ({sid}, {name}): {', '.join(stable)}")
            else:
                lines.append(f"{c.character_id} ({sid}, {name})")
        return "\n".join(lines) or "（无角色）"

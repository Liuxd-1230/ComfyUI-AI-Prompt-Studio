"""模型无关的分镜结构：Storyboard / Scene / Shot / Beat / StoryItem / StoryItemList。"""


import dataclasses
import time
from typing import List

from .base import Schema

SPLIT_MODES = ["scene", "shot", "beat", "auto"]
SELECT_MODES = ["scene", "shot", "range", "all"]


@dataclasses.dataclass
class Beat(Schema):
    """镜头内的最小节拍。"""

    beat_id: str = ""
    index: int = 0
    text: str = ""
    kind: str = "action"            # action | dialogue | transition | note
    characters: List[str] = dataclasses.field(default_factory=list)  # character_id
    audio: List[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class Shot(Schema):
    """单个镜头。"""

    shot_id: str = ""
    index: int = 0
    summary: str = ""
    action: str = ""
    beats: List[Beat] = dataclasses.field(default_factory=list)
    characters: List[str] = dataclasses.field(default_factory=list)
    camera: str = ""
    audio: List[str] = dataclasses.field(default_factory=list)
    duration: float = 0.0


@dataclasses.dataclass
class Scene(Schema):
    """场景（一场戏，可含多镜头）。"""

    scene_id: str = ""
    index: int = 0
    title: str = ""
    synopsis: str = ""
    location: str = ""
    characters: List[str] = dataclasses.field(default_factory=list)
    shots: List[Shot] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class ContinuityNote(Schema):
    """连续性说明（人物/场景一致性）。"""

    character_id: str = ""
    scene_ids: List[str] = dataclasses.field(default_factory=list)
    note: str = ""
    severity: str = "info"          # info | warning | error


@dataclasses.dataclass
class Storyboard(Schema):
    """故事的结构化拆分（模型无关，禁止硬编码 ANIMA/H3 标签）。"""

    story_id: str = ""
    title: str = ""
    summary: str = ""
    split_mode: str = "scene"
    style: str = ""
    characters: List[str] = dataclasses.field(default_factory=list)
    scenes: List[Scene] = dataclasses.field(default_factory=list)
    continuity: List[ContinuityNote] = dataclasses.field(default_factory=list)
    created_at: str = ""

    def __post_init__(self):
        import uuid

        if not self.story_id:
            self.story_id = "story_" + uuid.uuid4().hex[:8]
        if not self.created_at:
            self.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    def scene_by_id(self, scene_id: str) -> Scene | None:
        for s in self.scenes:
            if s.scene_id == scene_id:
                return s
        return None

    def shot_by_id(self, shot_id: str) -> Shot | None:
        for s in self.scenes:
            for sh in s.shots:
                if sh.shot_id == shot_id:
                    return sh
        return None

    def all_character_ids(self) -> List[str]:
        """返回故事中出现的全部人物 ID（档案级 + 场景 + 镜头，去重保序）。"""
        seen: List[str] = []
        for c in self.characters:
            if c not in seen:
                seen.append(c)
        for s in self.scenes:
            for c in s.characters:
                if c not in seen:
                    seen.append(c)
            for sh in s.shots:
                for c in sh.characters:
                    if c not in seen:
                        seen.append(c)
        return seen


@dataclasses.dataclass
class StoryItem(Schema):
    """一个可送入 Composer / H3 Director 的选择项（场景或镜头）。"""

    item_id: str = ""
    kind: str = "shot"              # scene | shot
    scene_id: str = ""
    shot_id: str = ""
    index: int = 0
    title: str = ""
    text: str = ""                  # 该条目的完整描述文本
    characters: List[str] = dataclasses.field(default_factory=list)
    scene_title: str = ""
    location: str = ""
    camera: str = ""


@dataclasses.dataclass
class StoryItemList(Schema):
    """批量选择结果，供 ComfyUI 批处理。"""

    mode: str = "all"
    selection: str = ""
    story_id: str = ""
    items: List[StoryItem] = dataclasses.field(default_factory=list)
    batch_count: int = 0

    def __post_init__(self):
        self.batch_count = len(self.items)

"""MiniMax H3 提示词计划：H3PromptPlan 及各子结构。

以官方 H3 手册为格式真源。
"""


import dataclasses
import time
from typing import Any, List, Optional

from .base import Schema
from .prompt_plan import ValidationReport, empty_validation

H3_MODES = ["T2VA", "I2VA", "FL2VA", "L2VA", "Ref2VA"]
H3_UI_MODES = H3_MODES

# Ref2VA 六段固定顺序
REF2VA_SECTIONS = [
    "subject_definitions",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
]

# 三字段固定顺序（T2VA/I2VA/FL2VA/L2VA）
THREE_FIELDS = [
    "integrated_multimodal_description",
    "overall_soundscape",
    "non_diegetic_music",
]


@dataclasses.dataclass
class H3Dialogue(Schema):
    """一句对白/歌词/画外音。原文语言在 <d>[Language] ...</d> 中逐字保留。"""

    language: str = "English"       # <d>[Language] 中的语言名
    text: str = ""
    speaker_ids: List[str] = dataclasses.field(default_factory=list)  # S1 / S2 / S1,S2
    kind: str = "speech"            # speech | singing | voiceover
    prefix_marker: str = ""          # <scenetrans>（跨切后半句）
    suffix_marker: str = ""          # <scenetrans> | <cutoff>
    lips_closed: bool = False         # voiceover 时必须为 True


@dataclasses.dataclass
class H3Shot(Schema):
    """一个镜头。start_time=None 表示 [Shot 1]（无时间戳）。"""

    index: int = 1
    start_time: Optional[float] = None   # 秒；Shot 1 为 None
    description: List[str] = dataclasses.field(default_factory=list)  # 描述句（英文）
    camera: str = ""                     # 自然英文相机运动
    camera_motion: str = ""              # push_in / pan_right / tracking / static ...
    camera_amplitude: str = ""           # small | normal | large
    camera_speed: str = ""               # slow | normal | fast
    camera_target: str = ""
    characters: List[str] = dataclasses.field(default_factory=list)   # speaker_ids 出现于本镜头
    dialogues: List[H3Dialogue] = dataclasses.field(default_factory=list)
    references: List[str] = dataclasses.field(default_factory=list)   # 用到的标签，如 "<Picture 1>"
    audio_notes: str = ""                # 本镜头内的音效/声音说明
    on_screen_text: List[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class H3Speaker(Schema):
    """说话人定义（跨镜头稳定 ID）。"""

    speaker_id: str = "S1"
    name: str = ""
    character_id: str = ""           # 对应 Character Bible
    description: str = ""            # 首次出现时的身份/音色描述（写在 <d> 外）


@dataclasses.dataclass
class H3Subject(Schema):
    """<Subject N>：可复用内容单元。"""

    label: str = "Subject 1"
    kind: str = "character"          # character | scene | object | clothing | style | other
    definition: str = ""             # 定义句（英文）
    source_assets: List[str] = dataclasses.field(default_factory=list)  # 如 "Picture 1"


@dataclasses.dataclass
class H3Asset(Schema):
    """<Picture N> / <Video N> / <Audio N>。"""

    label: str = "Picture 1"
    kind: str = "picture"            # picture | video | audio
    source: str = ""                 # 来源资产引用
    alignment_time: Optional[float] = None   # 图片对齐到目标视频的秒数
    note: str = ""


@dataclasses.dataclass
class H3Retention(Schema):
    """retention_analysis 一行：标签 + marker + 说明。"""

    label: str = ""
    marker: str = "fully_preserved"  # fully_preserved|partially_preserved|attribute_transfer|weak_reference|fully_copy|partially_copy|reference
    notes: str = ""
    shot_refs: List[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class H3AudioField(Schema):
    """soundscape / music 中的一条音频说明（或 <Audio N> 的 copy 状态）。"""

    label: str = ""
    kind: str = "soundscape"         # soundscape | music | audio_asset
    copy_status: str = ""            # fully_copy | partially_copy | reference | weak_reference（音频资产时）
    description: str = ""


@dataclasses.dataclass
class H3PromptPlan(Schema):
    """H3 结构化计划：LLM 产出内容决策，Python renderer 拼装最终格式。"""

    plan_id: str = ""
    mode: str = "T2VA"               # T2VA | I2VA | FL2VA | L2VA | Ref2VA
    duration_seconds: float = 0.0    # 有效视频时长 S.SS（两位小数）
    style_opening: str = ""          # Ref2VA 在 [Shot 1] 之前的风格开场（1-2 句）
    shots: List[H3Shot] = dataclasses.field(default_factory=list)
    speakers: List[H3Speaker] = dataclasses.field(default_factory=list)
    subjects: List[H3Subject] = dataclasses.field(default_factory=list)
    assets: List[H3Asset] = dataclasses.field(default_factory=list)
    retention: List[H3Retention] = dataclasses.field(default_factory=list)
    soundscape: str = ""             # overall_soundscape 正文
    explicit_silence: bool = False    # 仅用户明确要求全片静音时允许 soundscape=N/A
    non_diegetic_music: str = ""     # non_diegetic_music 正文（N/A 表示无）
    summary: str = ""                # Ref2VA summary 段（含任务前缀）
    storyboard_id: str = ""
    warnings: List[str] = dataclasses.field(default_factory=list)
    validation: ValidationReport = dataclasses.field(default_factory=empty_validation)
    raw: str = ""                    # LLM 原始输出（JSON）
    created_at: str = ""

    def __post_init__(self):
        import uuid

        if self.mode not in H3_MODES:
            raise ValueError(f"unsupported H3 mode: {self.mode!r}")
        if not self.plan_id:
            self.plan_id = "h3_" + uuid.uuid4().hex[:10]
        if not self.created_at:
            self.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    def speaker_ids(self) -> List[str]:
        return [s.speaker_id for s in self.speakers]

    def all_reference_labels(self) -> List[str]:
        labels = [s.label for s in self.subjects]
        labels += [a.label for a in self.assets]
        return labels

    def to_payload(self) -> dict:
        return self.to_json()

    def to_llm_context(self) -> dict[str, Any]:
        """Return only semantic facts needed for planning or refinement.

        Raw provider output, validation artifacts, warnings, timestamps, and
        generated identifiers are execution metadata and deliberately excluded.
        """
        data = self.to_json()
        for key in ("schema_version", "plan_id", "raw", "warnings",
                    "validation", "created_at"):
            data.pop(key, None)
        return _drop_empty(data)


def _drop_empty(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: cleaned for key, item in value.items()
                if (cleaned := _drop_empty(item)) not in (None, "", [], {})}
    if isinstance(value, list):
        return [cleaned for item in value
                if (cleaned := _drop_empty(item)) not in (None, "", [], {})]
    return value

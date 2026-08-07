"""参考资产与人物来源：AssetRef / SubjectRef / ReferenceAnalysis / ReferenceManifest。"""


import dataclasses
import time
from typing import Any, Dict, List, Optional

from .base import Schema

ANALYSIS_MODES = [
    "character_identity",
    "character_full",
    "clothing",
    "pose_expression",
    "scene",
    "composition",
    "style",
    "object",
    "anima_reference",
    "h3_reference",
    "custom",
]

ASSET_TYPES = ["image", "video", "audio", "text"]


@dataclasses.dataclass
class AssetRef(Schema):
    """一条原始参考资产（图片/视频/音频/文本）的注册记录。"""

    asset_id: str = ""
    asset_type: str = "image"
    path_or_ref: str = ""           # 文件路径或外部引用
    uri: str = ""                   # data URI / 内部引用（可选）
    data_ref: str = ""              # 内部数据句柄（如 ComfyUI 张量名），不持久化内容
    time_start: Optional[float] = None
    time_end: Optional[float] = None
    subject_ids: List[str] = dataclasses.field(default_factory=list)
    h3_labels: List[str] = dataclasses.field(default_factory=list)   # 如 "Picture 1"
    source: str = ""                # 来源描述（锚点/上传/节点输入）
    confidence: float = 1.0
    relationships: List[str] = dataclasses.field(default_factory=list)  # 与其他资产的关系
    note: str = ""

    def label_or_id(self) -> str:
        return self.h3_labels[0] if self.h3_labels else self.asset_id


@dataclasses.dataclass
class SubjectRef(Schema):
    """一个可复用内容单元（人物/场景/物件/风格），对应 H3 <Subject N>。"""

    subject_id: str = ""            # 如 "Subject 1"
    kind: str = "character"         # character | scene | object | clothing | style | other
    definition: str = ""
    source_assets: List[str] = dataclasses.field(default_factory=list)  # asset_id 列表
    confidence: float = 0.5
    locked: bool = False


@dataclasses.dataclass
class ReferenceAnalysis(Schema):
    """一次参考分析（文字/视觉）的结构化输出。"""

    analysis_id: str = ""
    mode: str = "character_full"
    summary: str = ""
    caption: str = ""               # 通用图注
    subjects: List[SubjectRef] = dataclasses.field(default_factory=list)
    assets: List[AssetRef] = dataclasses.field(default_factory=list)
    confidence: float = 0.5
    warnings: List[str] = dataclasses.field(default_factory=list)
    raw: str = ""                   # 模型原始 JSON/文本
    profile_id: str = ""
    created_at: str = ""

    def __post_init__(self):
        import uuid

        if not self.analysis_id:
            self.analysis_id = "anl_" + uuid.uuid4().hex[:10]
        if not self.created_at:
            self.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")


@dataclasses.dataclass
class ReferenceManifest(Schema):
    """参考资产清单：保留原始资产引用、Subject 映射、H3 标签、人物来源、时间裁剪与置信度。"""

    manifest_id: str = ""
    version: str = "1.0"
    assets: List[AssetRef] = dataclasses.field(default_factory=list)
    subjects: List[SubjectRef] = dataclasses.field(default_factory=list)
    character_sources: Dict[str, List[str]] = dataclasses.field(default_factory=dict)  # character_id -> asset_ids
    generated_at: str = ""
    notes: str = ""

    def __post_init__(self):
        import uuid

        if not self.manifest_id:
            self.manifest_id = "manf_" + uuid.uuid4().hex[:10]
        if not self.generated_at:
            self.generated_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    def asset_by_id(self, asset_id: str) -> Optional[AssetRef]:
        for a in self.assets:
            if a.asset_id == asset_id:
                return a
        return None

    def subject_by_id(self, subject_id: str) -> Optional[SubjectRef]:
        for s in self.subjects:
            if s.subject_id == subject_id:
                return s
        return None

    def add_asset(self, asset: AssetRef) -> "ReferenceManifest":
        self.assets.append(asset)
        return self

    def merge(self, other: "ReferenceManifest") -> "ReferenceManifest":
        """合并另一个清单（按 asset_id 去重，Subject 保留双方）。"""
        seen = {a.asset_id for a in self.assets}
        for a in other.assets:
            if a.asset_id not in seen:
                self.assets.append(a)
                seen.add(a.asset_id)
        seen_s = {s.subject_id for s in self.subjects}
        for s in other.subjects:
            if s.subject_id not in seen_s:
                self.subjects.append(s)
                seen_s.add(s.subject_id)
        for cid, asset_ids in other.character_sources.items():
            self.character_sources.setdefault(cid, [])
            for aid in asset_ids:
                if aid not in self.character_sources[cid]:
                    self.character_sources[cid].append(aid)
        return self

    def to_payload(self) -> Dict[str, Any]:
        return self.to_json()

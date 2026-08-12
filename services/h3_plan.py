"""H3 计划服务：结构化任务数据、输出解析与 manifest 映射。

LLM 负责「内容决策」（画面/声音/对白），Python renderer 负责「格式拼装」
（docs/adr/0004-deterministic-h3-rendering.md）。
"""
from __future__ import annotations

import re
from typing import List, Optional

from ..schemas.character import CharacterBible, CharacterBook
from ..schemas.h3 import (
    H3Asset,
    H3Dialogue,
    H3PromptPlan,
    H3Retention,
    H3Shot,
    H3Speaker,
    H3Subject,
)
from ..schemas.references import ReferenceManifest
from ..schemas.storyboard import Storyboard
from .reference import extract_json_object
from .json_schema import make_strict_schema

MODE_HINTS = {
    "T2VA": "纯文本转视频：从零构建完整视听时间线，无参考图。",
    "I2VA": "首帧锚定：<Picture 1> 即 [Shot 1] 的 0.00s 实际首帧，先确立风格/主体/构图再向前展开动作。",
    "FL2VA": "首尾帧路径：描述首帧到末帧的连续变化（运动、姿态、光照过渡），官方一般偏爱单镜头。",
    "L2VA": "尾帧收敛：<Picture 1> 是末帧，推断合理的前序状态并向末帧收敛。",
    "Ref2VA": "全参考重写：subject_definitions/summary/retention_analysis/detailed_description 六段。",
    "R2V": "全参考重写（旧名称，等同 Ref2VA）：六段固定结构。",
}

DIALOGUE_KINDS = ["speech", "singing", "voiceover"]
RETENTION_MARKERS = ["fully_preserved", "partially_preserved", "attribute_transfer",
                     "weak_reference", "fully_copy", "partially_copy", "reference"]

# 0.2.1 P1-17：H3 计划的原生 Structured Output JSON Schema。
# OutputContract 根据 provider 能力选择原生 Schema 或从同一 Schema 派生 fallback。
H3_SCHEMA = {
    "type": "object",
    "properties": {
        "style_opening": {"type": "string", "description": "R2V 风格开场（1-2 句，其他模式可空）"},
        "summary": {"type": "string", "description": "R2V summary 段全文（以 [任务类型] 前缀开头，其他模式可空）"},
        "speakers": {"type": "array", "items": {"type": "object",
            "properties": {"speaker_id": {"type": "string"}, "name": {"type": "string"},
                           "character_id": {"type": "string"},
                           "description": {"type": "string"}},
            "required": ["speaker_id"]}},
        "subjects": {"type": "array", "items": {"type": "object",
            "properties": {"label": {"type": "string"}, "kind": {"type": "string"},
                           "definition": {"type": "string"},
                           "source_assets": {"type": "array", "items": {"type": "string"}}},
            "required": ["label", "definition"]}},
        "assets": {"type": "array", "items": {"type": "object",
            "properties": {"label": {"type": "string"}, "kind": {"type": "string"},
                           "source": {"type": "string"},
                           "alignment_time": {"type": ["number", "null"]},
                           "note": {"type": "string"}},
            "required": ["label", "kind"]}},
        "retention": {"type": "array", "items": {"type": "object",
            "properties": {"label": {"type": "string"}, "marker": {"type": "string"},
                           "notes": {"type": "string"},
                           "shot_refs": {"type": "array", "items": {"type": "string"}}},
            "required": ["label", "marker"]}},
        "soundscape": {"type": "string"},
        "non_diegetic_music": {"type": "string"},
        "explicit_silence": {"type": "boolean"},
        "shots": {"type": "array", "items": {"type": "object",
            "properties": {
                "index": {"type": "integer"},
                "start_time": {"type": ["number", "null"],
                               "description": "Shot 1 为 null；后续严格递增"},
                "description": {"type": "array", "items": {"type": "string"}},
                "camera": {"type": "string"},
                "camera_motion": {"type": "string"},
                "camera_amplitude": {"type": "string"},
                "camera_speed": {"type": "string"},
                "camera_target": {"type": "string"},
                "characters": {"type": "array", "items": {"type": "string"}},
                "dialogues": {"type": "array", "items": {"type": "object",
                    "properties": {"language": {"type": "string"}, "text": {"type": "string"},
                                   "speaker_ids": {"type": "array", "items": {"type": "string"}},
                                   "kind": {"type": "string"},
                                   "prefix_marker": {"type": "string"},
                                   "suffix_marker": {"type": "string"},
                                   "lips_closed": {"type": "boolean"}},
                    "required": ["text"]}},
                "references": {"type": "array", "items": {"type": "string"}},
                "audio_notes": {"type": "string"},
                "on_screen_text": {"type": "array", "items": {"type": "string"}}},
            "required": ["index"]}},
    },
    "required": ["shots", "speakers", "subjects", "assets", "retention"],
}


H3_SCHEMA = make_strict_schema(H3_SCHEMA)


def build_plan_task_data(
    text: str,
    mode: str,
    duration: float,
    *,
    storyboard: Optional[Storyboard] = None,
    bible: Optional[CharacterBible] = None,
    book: Optional[CharacterBook] = None,
    manifest: Optional[ReferenceManifest] = None,
    image_count: int = 0,
    repair_issues: str = "",
) -> dict:
    """Build typed H3 task data without instruction prose or a copied schema."""
    character_data = None
    if book is not None and book.characters:
        character_data = book.to_json()
    elif bible is not None:
        character_data = bible.to_json()
    return {
        "user_task": (text or "").strip(),
        "mode": mode,
        "mode_hint": MODE_HINTS.get(mode, ""),
        "duration_seconds": float(duration),
        "image_count": int(image_count),
        "characters": character_data,
        "reference_manifest": manifest.to_json() if manifest is not None else None,
        "storyboard": storyboard.to_json() if storyboard is not None else None,
        "validation_issues": repair_issues or None,
    }


def parse_plan_json(raw: str, mode: str, duration: float,
                    storyboard_id: str = "") -> H3PromptPlan:
    """把 LLM 输出 JSON 容错解析为 H3PromptPlan（失败抛可读错误）。"""
    data = extract_json_object(raw)
    if data is None:
        raise ValueError("模型输出不是合法 JSON，无法构建 H3 计划；请重试。")
    plan = H3PromptPlan(mode=mode, duration_seconds=duration, raw=raw or "",
                        storyboard_id=storyboard_id)

    if isinstance(data.get("style_opening"), str):
        plan.style_opening = data["style_opening"].strip()
    if isinstance(data.get("summary"), str):
        plan.summary = data["summary"].strip()
    if isinstance(data.get("soundscape"), str):
        plan.soundscape = data["soundscape"].strip()
    if isinstance(data.get("non_diegetic_music"), str):
        plan.non_diegetic_music = data["non_diegetic_music"].strip()
    plan.explicit_silence = bool(data.get("explicit_silence", False))

    for sp in data.get("speakers") or []:
        if not isinstance(sp, dict):
            continue
        plan.speakers.append(H3Speaker(
            speaker_id=_s(sp.get("speaker_id")) or "S1",
            name=_s(sp.get("name")),
            character_id=_s(sp.get("character_id")),
            description=_s(sp.get("description"))))

    for su in data.get("subjects") or []:
        if not isinstance(su, dict):
            continue
        plan.subjects.append(H3Subject(
            label=_s(su.get("label")) or f"Subject {len(plan.subjects) + 1}",
            kind=_s(su.get("kind")) or "character",
            definition=_s(su.get("definition")),
            source_assets=_str_list(su.get("source_assets"))))

    for a in data.get("assets") or []:
        if not isinstance(a, dict):
            continue
        plan.assets.append(H3Asset(
            label=_s(a.get("label")) or f"Picture {len(plan.assets) + 1}",
            kind=_s(a.get("kind")) or "picture",
            source=_s(a.get("source")),
            alignment_time=_num(a.get("alignment_time")),
            note=_s(a.get("note"))))

    for r in data.get("retention") or []:
        if not isinstance(r, dict):
            continue
        marker = _s(r.get("marker")) or "fully_preserved"
        label = _s(r.get("label"))
        allowed = ({"fully_copy", "partially_copy", "reference", "weak_reference"}
                   if label.strip("<>").startswith("Audio ") else
                   {"fully_preserved", "partially_preserved", "attribute_transfer", "weak_reference"})
        if marker not in allowed:
            marker = "reference" if label.strip("<>").startswith("Audio ") else "fully_preserved"
        plan.retention.append(H3Retention(
            label=label,
            marker=marker,
            notes=_s(r.get("notes")),
            shot_refs=_str_list(r.get("shot_refs"))))

    prev_ts = 0.0
    for i, sh in enumerate(data.get("shots") or [], start=1):
        if not isinstance(sh, dict):
            continue
        start = _num(sh.get("start_time"))
        if i == 1:
            start = None
        elif start is None:
            start = min(prev_ts + max(duration / 20, 0.5), max(duration - 0.5, 0.5))
        start = max(float(start or 0), 0.0) if i > 1 else None
        if i > 1:
            start = max(start, prev_ts + 0.001)
            prev_ts = start
        dialogues = []
        for d in sh.get("dialogues") or []:
            if not isinstance(d, dict):
                continue
            kind = _s(d.get("kind")) or "speech"
            if kind not in DIALOGUE_KINDS:
                kind = "speech"
            dialogues.append(H3Dialogue(
                language=_s(d.get("language")) or "English",
                text=_s(d.get("text")),
                speaker_ids=_str_list(d.get("speaker_ids")),
                kind=kind,
                prefix_marker=_marker(d.get("prefix_marker")),
                suffix_marker=_marker(d.get("suffix_marker")),
                lips_closed=bool(d.get("lips_closed", kind == "voiceover"))))
        plan.shots.append(H3Shot(
            index=i, start_time=start,
            description=_str_list(sh.get("description")),
            camera=_s(sh.get("camera")),
            camera_motion=_s(sh.get("camera_motion")),
            camera_amplitude=_s(sh.get("camera_amplitude")),
            camera_speed=_s(sh.get("camera_speed")),
            camera_target=_s(sh.get("camera_target")),
            characters=_str_list(sh.get("characters")),
            dialogues=dialogues,
            references=_str_list(sh.get("references")),
            audio_notes=_s(sh.get("audio_notes")),
            on_screen_text=_str_list(sh.get("on_screen_text"))))
    return plan


def map_image_assets(plan: H3PromptPlan, image_count: int, mode: str) -> List[str]:
    """把输入图片映射为 Picture 资产（I2VA 首帧 / FL2VA 首尾 / L2VA 尾帧）。

    同时按模式校验资产约束（docs/decisions.md D18）：
    T2VA=0 图；I2VA=1（首帧）；FL2VA=2（首尾帧）；L2VA=1（尾帧）；R2V 不限。
    返回 warning 列表；约束不满足时给出明确 warning/error，不生成错误引用。
    """
    warnings: List[str] = []
    if mode == "T2VA" and image_count:
        warnings.append(f"T2VA 为纯文本模式，传入的 {image_count} 张图片将被忽略")
    if mode == "I2VA" and image_count != 1:
        warnings.append(f"I2VA 需要 1 张首帧参考图，实际 {image_count}（缺失则不应引用 <Picture 1>）")
    if mode == "FL2VA" and image_count != 2:
        warnings.append(f"FL2VA 需要 2 张参考图（首帧+尾帧），实际 {image_count}")
    if mode == "L2VA" and image_count != 1:
        warnings.append(f"L2VA 需要 1 张尾帧参考图，实际 {image_count}")

    existing = {a.label: a for a in plan.assets}
    for i in range(1, image_count + 1):
        label = f"Picture {i}"
        asset = existing.get(label)
        if mode == "I2VA" and i == 1:
            if asset:
                asset.source, asset.alignment_time = "1", 0.0
            else:
                plan.assets.append(H3Asset(label=label, kind="picture", source="1",
                                           alignment_time=0.0))
        elif mode == "FL2VA" and i in (1, image_count):
            source = "1" if i == 1 else str(len(plan.shots) or 1)
            alignment = 0.0 if i == 1 else plan.duration_seconds
            if asset:
                asset.source, asset.alignment_time = source, alignment
            else:
                plan.assets.append(H3Asset(label=label, kind="picture",
                                           source=source, alignment_time=alignment))
        elif mode == "L2VA" and i == image_count:
            source = str(len(plan.shots) or 1)
            if asset:
                asset.source, asset.alignment_time = source, plan.duration_seconds
            else:
                plan.assets.append(H3Asset(label=label, kind="picture",
                                           source=source,
                                           alignment_time=plan.duration_seconds))
        elif not asset:
            plan.assets.append(H3Asset(label=label, kind="picture"))
    return warnings


def sync_manifest_assets(plan: H3PromptPlan,
                         manifest: Optional[ReferenceManifest]) -> None:
    """确保连接的清单资产/主体进入最终计划，LLM 遗漏也不会静默丢失。"""
    if manifest is None:
        return
    existing_labels = {asset.label: asset for asset in plan.assets}
    counters = {"Picture": 0, "Video": 0, "Audio": 0}
    for asset in plan.assets:
        m = MEDIA_LABEL_RE.match(asset.label or "")
        if m:
            counters[m.group(1)] = max(counters[m.group(1)], int(m.group(2)))
    asset_labels: dict[str, str] = {}
    for source in manifest.assets:
        kind = "Picture" if source.asset_type == "image" else source.asset_type.title()
        if kind not in counters:
            continue
        preferred = next((label for label in source.h3_labels
                          if re.fullmatch(rf"{kind} \d+", label)), "")
        label = preferred
        if not label:
            counters[kind] += 1
            label = f"{kind} {counters[kind]}"
        else:
            number = int(label.rsplit(" ", 1)[1])
            counters[kind] = max(counters[kind], number)
        asset_labels[source.asset_id] = label
        if label not in existing_labels:
            item = H3Asset(label=label, kind=kind.lower(),
                           source=source.asset_id or source.path_or_ref,
                           note=source.note)
            plan.assets.append(item)
            existing_labels[label] = item
    for index, source in enumerate(manifest.subjects, start=1):
        label = f"Subject {index}"
        mapped = [asset_labels.get(asset_id, asset_id)
                  for asset_id in source.source_assets]
        existing = next((subject for subject in plan.subjects
                         if subject.label == label), None)
        if existing is None:
            plan.subjects.append(H3Subject(
                label=label, kind=source.kind, definition=_clean(source.definition),
                source_assets=mapped))
        else:
            existing.source_assets = list(dict.fromkeys(
                list(existing.source_assets) + mapped))


MEDIA_LABEL_RE = re.compile(r"^(Picture|Video|Audio)\s(\d+)$")


def normalize_media_labels(plan: H3PromptPlan) -> None:
    """把 Picture/Video/Audio 编号重排为按类型独立、1 起始连续（官方规则）。

    LLM 可能产出混合编号（如 Video 2 没有 Video 1）；渲染前由 Python 确定性修正，
    并同步 retention/参考里的引用。
    """
    kind_counter = {"Picture": 0, "Video": 0, "Audio": 0}
    mapping: dict = {}
    for asset in plan.assets:
        m = MEDIA_LABEL_RE.match(asset.label or "")
        if not m:
            continue
        kind, _ = m.group(1), m.group(2)
        kind_counter[kind] += 1
        new_label = f"{kind} {kind_counter[kind]}"
        if new_label != asset.label:
            mapping[asset.label] = new_label
            asset.label = new_label

    if not mapping:
        return
    for retention in plan.retention:
        if retention.label in mapping:
            retention.label = mapping[retention.label]
    for subject in plan.subjects:
        subject.source_assets = [mapping.get(a, a) for a in subject.source_assets]
    for shot in plan.shots:
        shot.references = [mapping.get(r, r) for r in shot.references]
    # 首行对齐指令中的 Picture 引用由 renderer 依据 assets 生成，无需改写


# ---------------------------------------------------------------- 工具

def _clean(text: str) -> str:
    """去除首尾空白。不做假装翻译（R2V 英文由 LLM/修复循环负责）。"""
    return (text or "").strip()


def _s(v) -> str:
    return str(v).strip() if v else ""


def _num(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _str_list(v) -> List[str]:
    if not isinstance(v, list):
        return []
    out = []
    for x in v:
        s = str(x).strip()
        if s and s not in out:
            out.append(s)
    return out


def _marker(value: object) -> str:
    marker = _s(value)
    return marker if marker in {"<scenetrans>", "<cutoff>"} else ""

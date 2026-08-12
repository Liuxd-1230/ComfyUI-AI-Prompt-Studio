"""H3 计划服务：LLM 指令构造、输出 JSON 容错解析、分镜转换、manifest 映射。

LLM 负责「内容决策」（画面/声音/对白），Python renderer 负责「格式拼装」
（docs/adr/0004-deterministic-h3-rendering.md）。
"""
from __future__ import annotations

import re
from typing import List, Optional

from ..schemas.character import CharacterBible, CharacterBook
from ..schemas.h3 import (
    H3Asset,
    H3AudioField,
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
from ..prompting.model_cores import model_core_prompt
from ..prompting.studio_policies import H3_CAMERA_VOCABULARY, H3_SHOT_COUNT_POLICY

MODE_HINTS = {
    "T2VA": "纯文本转视频：从零构建完整视听时间线，无参考图。",
    "I2VA": "首帧锚定：<Picture 1> 即 [Shot 1] 的 0.00s 实际首帧，先确立风格/主体/构图再向前展开动作。",
    "FL2VA": "首尾帧路径：描述首帧到末帧的连续变化（运动、姿态、光照过渡），官方一般偏爱单镜头。",
    "L2VA": "尾帧收敛：<Picture 1> 是末帧，推断合理的前序状态并向末帧收敛。",
    "Ref2VA": "全参考重写：subject_definitions/summary/retention_analysis/detailed_description 六段。",
    "R2V": "全参考重写（旧名称，等同 Ref2VA）：六段固定结构。",
}

# 内部系统提示词层（docs/prompt-audit.md H3-S-1）：协议规则固定在这一层，
# 用户消息只放任务上下文与请求，避免把规则与内容字符串拼接。
# 规则依据官方手册（docs/sources/minimax_h3_FL2V手册.html / r2v手册.html）。
def h3_system_prompt() -> str:
    """Return the immutable H3 Model Core for compatibility callers."""
    return model_core_prompt("minimax_h3")

DIALOGUE_KINDS = ["speech", "singing", "voiceover"]
RETENTION_MARKERS = ["fully_preserved", "partially_preserved", "attribute_transfer",
                     "weak_reference", "fully_copy", "partially_copy", "reference"]

# 0.2.1 P1-17：H3 计划的原生 Structured Output JSON Schema。
# Provider 支持（structured_output_responses/chat）→ GenerateRequest.output_schema 走协议层；
# 不支持 → 保留 build_plan_prompt 里的 JSON 模板提示词（不三重重复）。
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


def build_plan_prompt(
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
) -> str:
    """构造 H3 计划生成指令（要求输出 H3PromptPlan 对应的 JSON）。"""
    ctx = []
    if book is not None and book.characters:
        ctx.append(f"[角色表（Speaker ID 必须沿用，禁止自行发明 S 号）]\n{book.context_text()}")
    elif bible is not None and bible.character_prompt():
        ctx.append(f"[人物设定] {bible.character_prompt()}")
    if image_count:
        ctx.append(f"[参考图] 本模式提供 {image_count} 张参考图，按 <Picture 1..{image_count}> 引用。")
    if manifest is not None and manifest.to_json():
        ctx.append(f"[参考资产] 见以下清单：\n{_manifest_summary(manifest)}")
    if storyboard is not None and storyboard.scenes:
        ctx.append(f"[分镜] {_storyboard_summary(storyboard)}")
    ctx_text = ("\n".join(ctx) + "\n") if ctx else ""

    repair = (f"[需修复的校验问题]\n{repair_issues}\n" if repair_issues else "")

    return (
        "Build the H3 prompt plan for the task below. Output only the JSON object.\n"
        f"[模式] {mode}：{MODE_HINTS.get(mode, '')}\n"
        f"[目标时长] {duration:.2f} 秒\n"
        f"{ctx_text}{repair}"
        "[对白] 原文语言/标点逐字保留在 <d>[Language] ...</d>；说话人用稳定 S1/S2。\n"
        "[镜头] Shot 1 无时间戳；后续镜头 start_time 秒（严格递增且 < 目标时长）。\n"
        "[JSON 结构]\n"
        '{\n'
        '  "style_opening": "R2V 风格开场（1-2 句，其他模式可空）",\n'
        '  "summary": "R2V summary 段全文（以 [任务类型] 前缀开头，其他模式可空）",\n'
        '  "speakers": [{"speaker_id": "S1", "name": "", "description": "身份/音色描述"}],\n'
        '  "subjects": [{"label": "Subject 1", "kind": "character", '
        '"definition": "定义句（含 <Picture N> 来源引用）"}],\n'
        '  "assets": [{"label": "Picture 1", "kind": "picture", "source": "1", '
        '"alignment_time": 0.0}, {"label": "Audio 1", "kind": "audio", '
        '"source": "", "note": "音轨说明"}],\n'
        '  "retention": [{"label": "Subject 1", "marker": "fully_preserved", '
        '"notes": "保留说明", "shot_refs": ["Shot 1", "Shot 2"]}],\n'
        '  "soundscape": "overall_soundscape 全文（1-4 句，不重复对白）",\n'
        '  "non_diegetic_music": "non_diegetic_music 全文（1-3 句，无抽象情绪词；无则 N/A）",\n'
        '  "explicit_silence": false,\n'
        '  "shots": [{"index": 1, "start_time": null, '
        '"description": ["画面/动作英文描述句"], "camera": "兼容自由运镜句", '
        '"camera_motion": "push_in", "camera_amplitude": "small", '
        '"camera_speed": "slow", "camera_target": "the subject", '
        '"characters": ["S1"], "audio_notes": "", '
        '"dialogues": [{"language": "English", "text": "原文", '
        '"speaker_ids": ["S1"], "kind": "speech", "prefix_marker": "", '
        '"suffix_marker": "", "lips_closed": false}], "references": [], '
        '"on_screen_text": []}]\n'
        '}\n'
        f"[输入]\n{text}"
    )


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


# ---------------------------------------------------------------- 转换

def convert_storyboard(sb: Storyboard, mode: str, duration: float,
                       manifest: Optional[ReferenceManifest] = None,
                       book: Optional[CharacterBook] = None) -> H3PromptPlan:
    """把模型无关分镜转为 H3PromptPlan（结构映射；画面描述留给后续 LLM）。

    Speaker ID：有 CharacterBook 时沿用其稳定 ID（char→Sx 映射），
    否则按人物出现顺序自动 S1..Sn。
    """
    plan = H3PromptPlan(mode=mode, duration_seconds=duration,
                        storyboard_id=sb.story_id)
    plan.summary = f"[reference generation] {sb.summary or sb.title or ''}".strip()
    plan.style_opening = sb.style or ""

    # 镜头时间分布：按分镜时长均摊
    total_shots = sum(len(sc.shots) if sc.shots else 1 for sc in sb.scenes) or 1
    step = duration / total_shots
    shot_no = 0
    for sc in sb.scenes:
        shots = sc.shots or [_empty_shot()]
        for sh in shots:
            shot_no += 1
            start = None if shot_no == 1 else min(round(step * (shot_no - 1), 3),
                                                  max(duration - 0.001, 0))
            audio = [str(item).strip() for item in sh.audio if str(item).strip()]
            audio.extend(str(item).strip() for beat in sh.beats for item in beat.audio
                         if str(item).strip())
            plan.shots.append(H3Shot(
                index=shot_no, start_time=start,
                description=[_clean(sh.summary or sh.action or sc.title or "")],
                camera=_clean(sh.camera),
                characters=list(sh.characters),
                audio_notes="; ".join(dict.fromkeys(audio))))

    # 人物 → 说话人（优先沿用 CharacterBook 的稳定 Speaker ID）
    auto_no = 0
    for i, cid in enumerate(sb.all_character_ids(), start=1):
        speaker_id = book.speaker_id_for(cid) if book is not None else ""
        if not speaker_id:
            auto_no += 1
            speaker_id = f"S{auto_no}"
        book_character = book.get_character(cid) if book is not None else None
        storyboard_character = next(
            (item for item in sb.character_definitions if item.character_id == cid), None)
        name = (book_character.name if book_character is not None and book_character.name
                else storyboard_character.name if storyboard_character is not None
                else cid)
        plan.speakers.append(H3Speaker(speaker_id=speaker_id, character_id=cid,
                                       name=name))

    # manifest → subjects/assets/retention
    if manifest is not None:
        for i, subj in enumerate(manifest.subjects, start=1):
            plan.subjects.append(H3Subject(label=f"Subject {i}",
                                           kind=subj.kind,
                                           definition=_clean(subj.definition),
                                           source_assets=list(subj.source_assets)))
        # 图片/视频/音频按各自类型独立编号（官方规则）
        kind_counter = {"picture": 0, "video": 0, "audio": 0}
        for asset in manifest.assets:
            kind = "picture" if asset.asset_type == "image" else asset.asset_type
            if kind not in kind_counter:
                kind = "picture"
            kind_counter[kind] += 1
            plan.assets.append(H3Asset(label=f"{kind.capitalize()} {kind_counter[kind]}",
                                       kind=kind,
                                       source=asset.asset_id or asset.path_or_ref or "",
                                       note=asset.note))
        for i, subj in enumerate(manifest.subjects, start=1):
            plan.retention.append(H3Retention(
                label=f"Subject {i}", marker="fully_preserved",
                notes="沿用参考定义与特征", shot_refs=[f"Shot {j}" for j in range(1, len(plan.shots) + 1)]))
        # 离线结构映射没有模型替我们决定“参考在哪一镜生效”。保守地把每个
        # 已连接定义显式应用到所有镜头；用户可在导演工作台进一步收窄。
        for asset in plan.assets:
            marker = "reference" if asset.kind == "audio" else "fully_preserved"
            plan.retention.append(H3Retention(
                label=asset.label, marker=marker, notes="连接的参考资产",
                shot_refs=[f"Shot {j}" for j in range(1, len(plan.shots) + 1)]))
        labels = [subject.label for subject in plan.subjects] + [asset.label for asset in plan.assets]
        for shot in plan.shots:
            shot.references = list(dict.fromkeys([*shot.references, *labels]))
    sound_notes = [shot.audio_notes for shot in plan.shots if shot.audio_notes]
    if sound_notes:
        plan.soundscape = "; ".join(dict.fromkeys(sound_notes))
    else:
        plan.soundscape = ("Only natural environmental and physical action sounds directly "
                           "implied by each shot; no added dialogue or music.")
        plan.warnings.append("分镜没有声音说明；已使用仅限画面直接暗示声音的保守声景占位，请在生成前确认")
    plan.non_diegetic_music = "N/A"
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

def _manifest_summary(manifest: ReferenceManifest) -> str:
    lines = []
    for a in manifest.assets:
        lines.append(f"- {a.asset_id} ({a.asset_type}): {a.path_or_ref or a.note}")
    for s in manifest.subjects:
        lines.append(f"- {s.subject_id} ({s.kind}): {s.definition}")
    return "\n".join(lines) or "（无）"


def _storyboard_summary(sb: Storyboard) -> str:
    lines = []
    for sc in sb.scenes:
        for sh in (sc.shots or []):
            lines.append(f"- {sh.summary or sh.action} [camera: {sh.camera or '未指定'}]")
    return "\n".join(lines)


def _empty_shot():
    from ..schemas.storyboard import Shot

    return Shot(summary="")


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

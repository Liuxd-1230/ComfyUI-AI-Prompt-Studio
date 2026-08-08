"""MiniMax H3 提示词确定性渲染器（格式真源：官方手册，docs/research.md §5）。

五模式输出结构（严格按手册）：
- T2VA/I2VA/FL2VA/L2VA：首行对齐指令（I2VA/FL2VA/L2VA 有）+ 空行 + 三字段
  `integrated_multimodal_description` / `overall_soundscape` / `non_diegetic_music`；
  I2VA 首帧锚定、FL2VA 首尾帧路径（默认单镜头连续路径）、L2VA 尾帧收敛；
- R2V：六段 `subject_definitions` / `summary` / `retention_analysis` /
  `detailed_description`（风格开场在 [Shot 1] 之前）/ `overall_soundscape` / `non_diegetic_music`。
镜头：[Shot 1] 无时间戳；后续 `[Shot N] At MM:SS.mmm, ...`（严格递增）。
"""
from __future__ import annotations

import re
from typing import List, Optional

from ..schemas.h3 import (
    H3Dialogue,
    H3PromptPlan,
    H3Retention,
    H3Shot,
    H3Subject,
)


def format_timestamp(seconds: float) -> str:
    """秒 → MM:SS.mmm（两位分钟、三位毫秒）。"""
    total_ms = max(int(round(float(seconds) * 1000)), 0)
    mm, remainder = divmod(total_ms, 60_000)
    ss, mmm = divmod(remainder, 1000)
    return f"{mm:02d}:{ss:02d}.{mmm:03d}"


def render_dialogue(d: H3Dialogue, speaker_descriptions: Optional[dict[str, str]] = None,
                    introduced: Optional[set[str]] = None) -> str:
    ids = ",".join(d.speaker_ids)
    marker = f"({ids})" if ids else ""
    verb = {"singing": "sings", "voiceover": "says in an off-screen voiceover"}.get(
        d.kind, "says")
    prefix = ""
    if speaker_descriptions is not None and introduced is not None:
        new_descriptions = []
        for speaker_id in d.speaker_ids:
            if speaker_id not in introduced:
                description = speaker_descriptions.get(speaker_id, "").strip()
                if description:
                    new_descriptions.append(description)
                introduced.add(speaker_id)
        prefix = " and ".join(new_descriptions)
    spoken = f"{d.prefix_marker}{d.text}{d.suffix_marker}"
    line = f"{' '.join(p for p in (prefix, marker, verb) if p)}: <d>[{d.language or 'English'}] {spoken}</d>"
    if d.kind == "voiceover":
        line += " while the corresponding on-screen speaker's lips remain completely closed."
    return line


def render_shot(shot: H3Shot, speaker_descriptions: Optional[dict[str, str]] = None,
                introduced: Optional[set[str]] = None) -> str:
    parts = [s for s in shot.description if s]
    camera = _camera_text(shot)
    if camera:
        parts.append(camera.rstrip(".") + ".")
    if shot.references:
        labels = ", ".join(_angle_label(label) for label in shot.references)
        if not any(_angle_label(label) in " ".join(parts) for label in shot.references):
            parts.append(f"The referenced content {labels} takes effect in this shot.")
    if shot.audio_notes:
        parts.append(shot.audio_notes.rstrip(".") + ".")
    for visible_text in shot.on_screen_text:
        escaped = visible_text.replace('"', '\\"')
        parts.append(f'The visible on-screen text reads "{escaped}".')
    for d in shot.dialogues:
        parts.append(render_dialogue(d, speaker_descriptions, introduced))
    body = " ".join(parts)
    if shot.index <= 1 or shot.start_time is None:
        return f"[Shot {shot.index}] {body}".strip()
    return f"[Shot {shot.index}] At {format_timestamp(shot.start_time)}, {body}"


def render_h3(plan: H3PromptPlan) -> str:
    """H3PromptPlan → 最终提示词（确定性，无 LLM）。"""
    if plan.mode in {"R2V", "Ref2VA"}:
        return _render_r2v(plan)
    return _render_four_mode(plan)


# ---------------------------------------------------------------- 四模式

def _render_four_mode(plan: H3PromptPlan) -> str:
    instruction = _alignment_instruction(plan)
    body = _shots_text(plan)
    sound = _soundscape_text(plan)
    music = plan.non_diegetic_music.strip() or "N/A"
    fields = [
        f"integrated_multimodal_description: {body}",
        f"overall_soundscape: {sound}",
        f"non_diegetic_music: {music}",
    ]
    if instruction:
        return instruction + "\n\n" + "\n".join(fields)
    return "\n".join(fields)


def _alignment_instruction(plan: H3PromptPlan) -> str:
    """I2VA/FL2VA/L2VA 首行对齐指令（官方句式，Python 确定性生成）。"""
    mode = plan.mode
    if mode == "T2VA":
        return ""
    last_shot = plan.shots[-1].index if plan.shots else 1
    dur = f"{plan.duration_seconds:.2f}"

    if mode == "I2VA":
        return ("For the target video, at 0.00 seconds into the target video, "
                "<Picture 1> (from [Shot 1]) is fully referenced.")

    if mode == "FL2VA":
        pics = [a for a in plan.assets if a.kind == "picture"]
        if len(pics) >= 2:
            p1, pN = pics[0], pics[-1]
            t1 = f"{p1.alignment_time:.2f}" if p1.alignment_time is not None else "0.00"
            tN = (f"{pN.alignment_time:.2f}" if pN.alignment_time is not None else dur)
            s1 = _label_num(p1.label, 1)
            sN = _label_num(pN.label, len(pics))
            return (
                "How the reference pictures align with the target video — "
                f"Picture {s1} (from Shot {_shot_of(p1, 1)}) aligns with the "
                f"{t1}-second mark of the target video; Picture {sN} "
                f"(from Shot {_shot_of(pN, last_shot)}) aligns with the "
                f"{tN}-second mark of the target video.")
        # 默认单镜头连续路径（官方：一般偏爱单镜头）
        return (
            "How the reference pictures align with the target video — "
            f"Picture 1 (from Shot 1) aligns with the 0.00-second mark of the "
            f"target video; Picture 2 (from Shot {last_shot}) aligns with the "
            f"{dur}-second mark of the target video.")

    if mode == "L2VA":
        return (
            "How the reference pictures align with the target video — "
            f"<Picture 1> (from [Shot {last_shot}]) aligns with the "
            f"{dur}-second mark of the target video.")
    return ""


def _shot_of(asset, default: int) -> int:
    m = re.search(r"(\d+)", asset.source or "")
    if m:
        return int(m.group(1))
    return default


def _label_num(label: str, default: int) -> int:
    m = re.search(r"(\d+)", label or "")
    return int(m.group(1)) if m else default


def _soundscape_text(plan: H3PromptPlan) -> str:
    if plan.explicit_silence:
        return "N/A"
    return plan.soundscape.strip()


# ---------------------------------------------------------------- R2V

def _render_r2v(plan: H3PromptPlan) -> str:
    lines: List[str] = []

    lines.append("subject_definitions:")
    for subj in plan.subjects:
        lines.append(_render_subject(subj))
    subject_sources = {source.strip("<>") for subject in plan.subjects
                       for source in subject.source_assets}
    for asset in plan.assets:
        if (asset.kind == "audio" or asset.label not in subject_sources or
                asset.alignment_time is not None or asset.note.strip()):
            note = asset.note.strip() or asset.source or f"a {asset.kind} reference"
            lines.append(f"<{asset.label}> is {note}.")

    lines.append("summary:")
    lines.append(plan.summary.strip() if plan.summary.strip() else "[reference generation]")

    lines.append("retention_analysis:")
    for r in plan.retention:
        lines.append(_render_retention(r))

    lines.append("detailed_description:")
    if plan.style_opening and plan.style_opening.strip():
        lines.append(plan.style_opening.strip())
    lines.extend(_shots_text(plan, join=False))

    lines.append("overall_soundscape:")
    lines.append(_soundscape_text(plan))

    lines.append("non_diegetic_music:")
    lines.append(plan.non_diegetic_music.strip() or "N/A")
    return "\n".join(lines)


def _render_subject(subj: H3Subject) -> str:
    definition = subj.definition.strip() or "a reusable content unit"
    sources = [_angle_label(source) for source in subj.source_assets]
    missing = [source for source in sources if source not in definition]
    if missing:
        definition += f", derived from {', '.join(missing)}"
    return f"<{subj.label}> is {definition}."


def _render_retention(r: H3Retention) -> str:
    label = r.label
    if re.search(r"^(Picture|Video|Audio)\s", label, re.I) or label.startswith(("Picture", "Video", "Audio")):
        return f"<{label}>: {r.marker} - {r.notes}".strip(" -")
    refs = ", ".join(f"[{s}]" for s in r.shot_refs)
    if refs:
        return f"<{label}> (appears in {refs}): {r.marker} - {r.notes}".rstrip(" -")
    return f"<{label}>: {r.marker} - {r.notes}".rstrip(" -")


def _shots_text(plan: H3PromptPlan, *, join: bool = True):
    descriptions = {speaker.speaker_id: speaker.description for speaker in plan.speakers}
    introduced: set[str] = set()
    lines = [render_shot(shot, descriptions, introduced) for shot in plan.shots]
    return " ".join(lines) if join else lines


def _angle_label(label: str) -> str:
    clean = (label or "").strip().strip("<>")
    return f"<{clean}>" if clean else ""


def _camera_text(shot: H3Shot) -> str:
    if shot.camera_motion:
        motion = shot.camera_motion.replace("_", " ")
        parts = [f"The camera {motion}"]
        if shot.camera_amplitude and shot.camera_amplitude != "normal":
            parts.append(f"with {shot.camera_amplitude} amplitude")
        if shot.camera_speed and shot.camera_speed != "normal":
            parts.append(f"at {shot.camera_speed} speed")
        if shot.camera_target:
            parts.append(f"toward {shot.camera_target}")
        return " ".join(parts)
    return shot.camera

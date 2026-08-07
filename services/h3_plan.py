"""H3 计划服务：LLM 指令构造、输出 JSON 容错解析、分镜转换、manifest 映射。

LLM 负责「内容决策」（画面/声音/对白），Python renderer 负责「格式拼装」
（docs/adr/0004-deterministic-h3-rendering.md）。
"""
from __future__ import annotations

import re
from typing import List, Optional

from ..schemas.character import CharacterBible
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

MODE_HINTS = {
    "T2VA": "纯文本转视频：从零构建完整视听时间线，无参考图。",
    "I2VA": "首帧锚定：<Picture 1> 即 [Shot 1] 的 0.00s 实际首帧，先确立风格/主体/构图再向前展开动作。",
    "FL2VA": "首尾帧路径：描述首帧到末帧的连续变化（运动、姿态、光照过渡），官方一般偏爱单镜头。",
    "L2VA": "尾帧收敛：<Picture 1> 是末帧，推断合理的前序状态并向末帧收敛。",
    "R2V": "全参考重写：subject_definitions/summary/retention_analysis/detailed_description 六段。",
}

DIALOGUE_KINDS = ["speech", "singing", "voiceover"]
RETENTION_MARKERS = ["fully_preserved", "partially_preserved", "attribute_transfer",
                     "weak_reference", "fully_copy", "partially_copy", "reference"]


def build_plan_prompt(
    text: str,
    mode: str,
    duration: float,
    *,
    storyboard: Optional[Storyboard] = None,
    bible: Optional[CharacterBible] = None,
    manifest: Optional[ReferenceManifest] = None,
    image_count: int = 0,
    repair_issues: str = "",
) -> str:
    """构造 H3 计划生成指令（要求输出 H3PromptPlan 对应的 JSON）。"""
    ctx = []
    if bible is not None and bible.character_prompt():
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
        "你是 MiniMax H3 视频提示词专家。根据输入生成结构化计划，只输出 JSON，不要其他文本。\n"
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
        '  "shots": [{"index": 1, "start_time": null, '
        '"description": ["画面/动作英文描述句"], "camera": "The camera ...", '
        '"characters": ["S1"], "audio_notes": "", '
        '"dialogues": [{"language": "English", "text": "原文", '
        '"speaker_ids": ["S1"], "kind": "speech"}]}]\n'
        '}\n'
        f"[输入]\n{text}"
    )


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
        if marker not in RETENTION_MARKERS:
            marker = "fully_preserved"
        plan.retention.append(H3Retention(
            label=_s(r.get("label")),
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
                kind=kind))
        plan.shots.append(H3Shot(
            index=i, start_time=start,
            description=_str_list(sh.get("description")),
            camera=_s(sh.get("camera")),
            characters=_str_list(sh.get("characters")),
            dialogues=dialogues,
            references=_str_list(sh.get("references")),
            audio_notes=_s(sh.get("audio_notes"))))
    return plan


# ---------------------------------------------------------------- 转换

def convert_storyboard(sb: Storyboard, mode: str, duration: float,
                       manifest: Optional[ReferenceManifest] = None) -> H3PromptPlan:
    """把模型无关分镜转为 H3PromptPlan（结构映射；画面描述留给后续 LLM）。"""
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
            plan.shots.append(H3Shot(
                index=shot_no, start_time=start,
                description=[_en(sh.summary or sh.action or sc.title or "")],
                camera=_en(sh.camera),
                characters=list(sh.characters),
                audio_notes=""))

    # 人物 → 说话人
    for i, cid in enumerate(sb.all_character_ids(), start=1):
        plan.speakers.append(H3Speaker(speaker_id=f"S{i}", character_id=cid,
                                       name=cid))

    # manifest → subjects/assets/retention
    if manifest is not None:
        for i, subj in enumerate(manifest.subjects, start=1):
            plan.subjects.append(H3Subject(label=f"Subject {i}",
                                           kind=subj.kind,
                                           definition=_en(subj.definition),
                                           source_assets=list(subj.source_assets)))
        for i, asset in enumerate(manifest.assets, start=1):
            kind = "picture" if asset.asset_type == "image" else asset.asset_type
            if kind not in ("picture", "video", "audio"):
                kind = "picture"
            plan.assets.append(H3Asset(label=f"{kind.capitalize()} {i}",
                                       kind=kind,
                                       source=asset.path_or_ref,
                                       note=asset.note))
        for i, subj in enumerate(manifest.subjects, start=1):
            plan.retention.append(H3Retention(
                label=f"Subject {i}", marker="fully_preserved",
                notes="沿用参考定义与特征", shot_refs=[f"Shot {j}" for j in range(1, len(plan.shots) + 1)]))
    return plan


def map_image_assets(plan: H3PromptPlan, image_count: int, mode: str) -> None:
    """把输入图片映射为 Picture 资产（I2VA 首帧 / FL2VA 首尾 / L2VA 尾帧）。"""
    existing = {a.label for a in plan.assets}
    for i in range(1, image_count + 1):
        label = f"Picture {i}"
        if label in existing:
            continue
        if mode == "I2VA" and i == 1:
            plan.assets.append(H3Asset(label=label, kind="picture", source="1",
                                       alignment_time=0.0))
        elif mode == "FL2VA" and i in (1, image_count):
            plan.assets.append(H3Asset(
                label=label, kind="picture",
                source="1" if i == 1 else str(len(plan.shots) or 1),
                alignment_time=0.0 if i == 1 else plan.duration_seconds))
        elif mode == "L2VA" and i == image_count:
            plan.assets.append(H3Asset(
                label=label, kind="picture",
                source=str(len(plan.shots) or 1),
                alignment_time=plan.duration_seconds))
        else:
            plan.assets.append(H3Asset(label=label, kind="picture"))


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


def _en(text: str) -> str:
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

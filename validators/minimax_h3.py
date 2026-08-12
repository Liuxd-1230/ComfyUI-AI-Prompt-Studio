"""MiniMax H3 提示词校验器（规则来自官方手册，docs/research.md §5）。

结构性规则（错误级）：六段/三字段顺序、[Shot 1] 无时间戳、时间戳严格递增、
MM:SS.mmm 格式、I2VA/FL2VA/L2VA 首行对齐指令、FL2VA 两位小数时长、
标签编号连续、<d>[Language]</d> 配对。
内容性规则（警告级）：soundscape 不重复对白、non_diegetic_music 无抽象情绪词、
R2V 风格开场位置、音频不重复。
"""
from __future__ import annotations

import re
from typing import Dict, List

from ..schemas.prompt_plan import ValidationReport

FOUR_MODE_FIELDS = ["integrated_multimodal_description",
                    "overall_soundscape", "non_diegetic_music"]
R2V_SECTION_HEADINGS = ["subject_definitions", "summary", "retention_analysis",
                        "detailed_description", "overall_soundscape",
                        "non_diegetic_music"]

LABEL_RE = re.compile(r"<(Subject|Picture|Video|Audio)\s(\d+)>")
SHOT_RE = re.compile(r"\[Shot\s(\d+)\](?:\s+At\s+(\d{2}:\d{2}\.\d{3}))?")
DIALOGUE_RE = re.compile(r"<d>\[([^\]]+)\](.*?)</d>", re.S)
SPEAKER_RE = re.compile(r"\(S\d+(?:,S\d+)*\)")

# 官方明确禁止的抽象情绪词（non_diegetic_music 段）
ABSTRACT_MOOD_WORDS = [
    "sad", "happy", "sadness", "joy", "joyful", "emotional", "melancholic",
    "mood", "atmosphere of", "feel", "feeling", "somber", "cheerful",
    "悲伤", "快乐", "情绪",
]

TIMESTAMP_RE = re.compile(r"^\d{2}:\d{2}\.\d{3}$")
# 用于捕获「有 At 前缀但格式不对」的畸形时间戳
AT_RE = re.compile(r"\bAt\s+(\d[\d:.]*)")


def _parse_timestamp_ms(ts: str) -> int:
    mm, rest = ts.split(":")
    ss, mmm = rest.split(".")
    return int(mm) * 60000 + int(ss) * 1000 + int(mmm)


def validate_h3(prompt: str, mode: str = "T2VA", *, duration: float | None = None,
                manifest=None, plan=None) -> ValidationReport:
    report = ValidationReport()
    report.checks.append(f"h3_{mode}")
    if not prompt or not prompt.strip():
        report.add("error", "h3_empty", "提示词为空")
        return report
    if duration is not None and not 4.0 <= float(duration) <= 15.0:
        report.add("error", "h3_duration", "MiniMax H3 目标时长必须在 4–15 秒")

    # 1) 段/字段结构
    if mode in {"R2V", "Ref2VA"}:
        _check_section_order(report, prompt, R2V_SECTION_HEADINGS, "h3_section")
        _check_r2v_style_opening(report, prompt)
        _check_retention_markers(report, prompt)
        _check_summary_prefix(report, prompt)
        _check_ref_detail_density(report, prompt)
        bad = r2v_english_issue(prompt)
        if bad:
            report.add("warning", "h3_r2v_english",
                       f"R2V 语义段 {bad!r} 含大量非英语内容（官方要求英文正文；"
                       f"对白/歌词/画面文字除外）；节点会自动尝试一次翻译修复")
    else:
        _check_section_order(report, prompt, FOUR_MODE_FIELDS, "h3_field")
        _check_alignment_instruction(report, prompt, mode)

    # 2) 镜头与时间戳（只在描述字段/段内检查，避免把指令行与 retention 的
    #    [Shot N] 引用误当镜头）
    _check_shots(report, prompt, mode, duration)

    # 3) 标签编号
    _check_labels(report, prompt)

    # 4) 对白 <d>[Language]</d>
    _check_dialogues(report, prompt)

    # 5) 说话人 ID
    _check_speakers(report, prompt)

    # 6) 音频段内容规则
    _check_soundscape(report, prompt)
    _check_music(report, prompt, mode)
    if manifest is not None and mode in {"R2V", "Ref2VA"}:
        _check_reference_limits(report, manifest)
    _check_unresolved_references(report, prompt)
    # T2VA is text-only. A manifest may still travel through a larger workflow,
    # but its assets are not mandatory references for this generation mode.
    if plan is not None and mode != "T2VA":
        _check_plan_references(report, plan, mode)
    if plan is not None:
        _check_plan_speakers(report, plan)
    return report


# ---------------------------------------------------------------- 结构

def _check_section_order(report, prompt, headings: List[str], code_prefix: str) -> None:
    pos = -1
    found = []
    for h in headings:
        idx = prompt.find(f"{h}:")
        if idx == -1:
            report.add("error", f"{code_prefix}_missing", f"缺少段/字段 {h!r}")
            continue
        if idx < pos:
            report.add("error", f"{code_prefix}_order", f"段/字段顺序错误：{h!r} 应在更靠后的位置")
        pos = idx
        found.append(h)
    if len(found) < len(headings):
        report.add("error", f"{code_prefix}_incomplete",
                   f"需要 {len(headings)} 段/字段，实际只有 {len(found)}")


def _check_alignment_instruction(report, prompt, mode: str) -> None:
    if mode == "T2VA":
        if prompt.strip().startswith("How the reference pictures align") or \
           prompt.strip().startswith("For the target video"):
            report.add("error", "h3_instruction_unexpected", "T2VA 不应有图像对齐指令行")
        return
    if mode == "I2VA":
        if not prompt.strip().startswith("For the target video, at 0.00 seconds"):
            report.add("error", "h3_i2va_instruction",
                       "I2VA 首行必须是：For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.")
    elif mode == "FL2VA":
        if not prompt.strip().startswith("How the reference pictures align with the target video"):
            report.add("error", "h3_fl2va_instruction",
                       "FL2VA 首行必须以 'How the reference pictures align with the target video —' 开头")
        marks = re.findall(r"(\d+\.\d+)-second mark", prompt[:400])
        for m in marks:
            if len(m.split(".")[1]) != 2:
                report.add("error", "h3_fl2va_2dp",
                           f"FL2VA 对齐秒数必须两位小数（发现 {m!r}）")
    elif mode == "L2VA":
        if not prompt.strip().startswith("How the reference pictures align with the target video"):
            report.add("error", "h3_l2va_instruction",
                       "L2VA 首行必须以 'How the reference pictures align with the target video —' 开头")
        if "<Picture 1>" not in prompt[:200]:
            report.add("error", "h3_l2va_picture", "L2VA 对齐指令须引用 <Picture 1>")


# ---------------------------------------------------------------- 镜头

def _check_shots(report, prompt, mode: str, duration: float | None = None) -> None:
    heading = ("integrated_multimodal_description" if mode not in {"R2V", "Ref2VA"}
               else "detailed_description")
    section = _section_text(prompt, heading)
    shots = SHOT_RE.findall(section)
    if not shots:
        report.add("error", "h3_no_shots", "未找到 [Shot N] 标记")
        return

    # 有 At 前缀但格式不对 → h3_ts_format
    for m in AT_RE.finditer(section):
        if not TIMESTAMP_RE.match(m.group(1)):
            report.add("error", "h3_ts_format",
                       f"时间戳格式错误：{m.group(1)!r}（应为 MM:SS.mmm）")
            break

    seen_index = 0
    prev_ms = -1
    for idx_str, ts in shots:
        idx = int(idx_str)
        if idx != seen_index + 1:
            report.add("error", "h3_shot_numbering",
                       f"镜头编号不连续：期望 {seen_index + 1}，实际 {idx}")
        seen_index = idx

        if idx == 1:
            if ts:
                report.add("error", "h3_shot1_timestamp",
                           "[Shot 1] 不应有时间戳")
        else:
            if not ts:
                report.add("error", "h3_shot_missing_ts",
                           f"[Shot {idx}] 缺少 'At MM:SS.mmm' 时间戳")
            else:
                if not TIMESTAMP_RE.match(ts):
                    report.add("error", "h3_ts_format",
                               f"时间戳格式错误：{ts!r}（应为 MM:SS.mmm）")
                else:
                    ms = _parse_timestamp_ms(ts)
                    if ms <= prev_ms:
                        report.add("error", "h3_ts_increasing",
                                   f"时间戳未严格递增：{ts!r}")
                    prev_ms = ms
                    if duration is not None and ms >= int(round(duration * 1000)):
                        report.add("error", "h3_ts_duration",
                                   f"镜头时间戳 {ts!r} 必须小于目标时长 {duration:.2f} 秒")


# ---------------------------------------------------------------- 标签

def _check_labels(report, prompt) -> None:
    by_type: Dict[str, List[int]] = {}
    for label_type, num in LABEL_RE.findall(prompt):
        by_type.setdefault(label_type, []).append(int(num))
    for label_type, nums in by_type.items():
        if not nums:
            continue
        for expected, n in enumerate(sorted(set(nums)), start=1):
            if n != expected:
                report.add("error", "h3_label_numbering",
                           f"<{label_type} N> 编号不连续：期望 {expected}，发现 {n}")


# ---------------------------------------------------------------- 对白

def _check_dialogues(report, prompt) -> None:
    opens = len(re.findall(r"<d>", prompt))
    closes = len(re.findall(r"</d>", prompt))
    if opens != closes:
        report.add("error", "h3_dialogue_unbalanced",
                   f"<d>/</d> 不配对（{opens} 开 / {closes} 闭）")
    # <d> 后必须紧跟 [Language]（空格容忍）
    for m in re.finditer(r"<d>", prompt):
        if not prompt[m.end():].lstrip().startswith("["):
            report.add("error", "h3_dialogue_language", "对白缺少 [Language] 语言标注")
            break
    for lang, content in DIALOGUE_RE.findall(prompt):
        if not content.strip():
            report.add("warning", "h3_dialogue_empty", f"对白 <d>[{lang}]</d> 内容为空")


# ---------------------------------------------------------------- 说话人

def _check_speakers(report, prompt) -> None:
    for m in SPEAKER_RE.findall(prompt):
        ids = m.strip("()").split(",")
        for sid in ids:
            if not re.fullmatch(r"S\d+", sid):
                report.add("warning", "h3_speaker_format", f"说话人 ID 格式错误：{sid!r}")


# ---------------------------------------------------------------- 音频段

def _check_soundscape(report, prompt) -> None:
    soundscape = _section_text(prompt, "overall_soundscape")
    if not soundscape.strip():
        report.add("error", "h3_soundscape_empty",
                   "overall_soundscape 为空；仅明确要求全片静音时可写 N/A")
    if soundscape and "<d>" in soundscape:
        report.add("warning", "h3_soundscape_dialogue",
                   "overall_soundscape 不应重复对白/歌词内容")


def _check_music(report, prompt, mode: str) -> None:
    music = _section_text(prompt, "non_diegetic_music")
    if music:
        low = music.lower()
        for w in ABSTRACT_MOOD_WORDS:
            if re.search(rf"\b{re.escape(w)}\b", low):
                report.add("warning", "h3_music_abstract",
                           f"non_diegetic_music 出现抽象情绪词 {w!r}（官方要求描述配器/速度/力度）")
                break
    sound = _section_text(prompt, "overall_soundscape")
    if music and sound and music.strip() == sound.strip():
        report.add("warning", "h3_audio_duplicate",
                   "overall_soundscape 与 non_diegetic_music 内容重复")


def _section_text(prompt: str, heading: str) -> str:
    """提取某段/字段的正文（四模式为行内，R2V 为换行后到下一标题）。"""
    start = prompt.find(f"{heading}:")
    if start == -1:
        return ""
    start += len(heading) + 1
    candidates = ["subject_definitions:", "summary:", "retention_analysis:",
                  "detailed_description:", "overall_soundscape:",
                  "non_diegetic_music:", "integrated_multimodal_description:"]
    end = len(prompt)
    for other in candidates:
        if other == f"{heading}:":
            continue
        idx = prompt.find(other, start)
        if idx != -1 and idx < end:
            end = idx
    return prompt[start:end].strip()


def _check_r2v_style_opening(report, prompt) -> None:
    dd = _section_text(prompt, "detailed_description")
    first_shot = dd.find("[Shot 1]")
    if first_shot == 0:
        report.add("warning", "h3_r2v_style_opening",
                   "R2V detailed_description 建议在 [Shot 1] 前有 1-2 句风格开场")


def _check_retention_markers(report, prompt) -> None:
    visual = {"fully_preserved", "partially_preserved", "attribute_transfer", "weak_reference"}
    audio = {"fully_copy", "partially_copy", "reference", "weak_reference"}
    markers = visual | audio
    section = _section_text(prompt, "retention_analysis")
    for line in section.splitlines():
        if not line.strip():
            continue
        match = re.search(r"<(Subject|Picture|Video|Audio)\s+\d+>\s*:\s*([a-z_]+)", line)
        if not match or match.group(2) not in markers:
            report.add("warning", "h3_retention_marker",
                       f"retention_analysis 行缺少合法 marker：{line.strip()[:60]}")
            continue
        label_type, marker = match.groups()
        allowed = audio if label_type == "Audio" else visual
        if marker not in allowed:
            report.add("error", "h3_retention_modality",
                       f"<{label_type}> 不能使用 {marker!r}；该 marker 与资产模态不匹配")


def _check_summary_prefix(report, prompt) -> None:
    summary = _section_text(prompt, "summary")
    if summary and not summary.startswith("["):
        report.add("error", "h3_summary_prefix",
                   "R2V summary 必须以方括号任务类型前缀开头，如 [reference generation]")
    match = re.match(r"\[([^\]]+)\]", summary)
    if match:
        allowed = {"keyframe completion", "reference generation", "video editing",
                   "video continuation", "audio reuse", "audio reference"}
        kinds = {part.strip().lower() for part in re.split(r"[+,/]", match.group(1))}
        unknown = kinds - allowed
        if unknown:
            report.add("error", "h3_summary_task_type",
                       f"未知 Ref2VA 任务类型：{', '.join(sorted(unknown))}")


def _check_ref_detail_density(report, prompt: str) -> None:
    detail = _section_text(prompt, "detailed_description")
    words = re.findall(r"\b[A-Za-z][A-Za-z'-]*\b", detail)
    if len(words) < 350 or len(words) > 500:
        report.add("warning", "h3_ref_word_count",
                   f"Ref2VA detailed_description 当前约 {len(words)} 个英文词；"
                   "生成类任务通常建议 350–500 词")


def _check_reference_limits(report, manifest) -> None:
    counts = {"image": 0, "video": 0, "audio": 0}
    totals = {"video": 0.0, "audio": 0.0}
    for asset in getattr(manifest, "assets", []):
        if asset.asset_type in counts:
            counts[asset.asset_type] += 1
        if asset.asset_type in {"video", "audio"}:
            if asset.time_start is None or asset.time_end is None:
                report.add("error", "h3_reference_duration_unknown",
                           f"{asset.asset_id or asset.asset_type} 无法验证时长；Ref2VA 必须提供可解析的 2–15 秒裁剪范围")
            else:
                length = asset.time_end - asset.time_start
                totals[asset.asset_type] += max(length, 0.0)
                if length < 2 or length > 15:
                    report.add("error", "h3_reference_duration",
                               f"{asset.asset_id or asset.asset_type} 时长 {length:.2f} 秒，官方范围为 2–15 秒")
    if counts["image"] > 9:
        report.add("error", "h3_reference_images", "Ref2VA 最多允许 9 张图片")
    if counts["video"] > 3:
        report.add("error", "h3_reference_videos", "Ref2VA 最多允许 3 个视频")
    if counts["audio"] > 3:
        report.add("error", "h3_reference_audio", "Ref2VA 最多允许 3 个音频")
    if sum(counts.values()) > 12:
        report.add("error", "h3_reference_total", "Ref2VA 混合参考文件总数最多为 12")
    if counts["audio"] and not (counts["image"] or counts["video"]):
        report.add("error", "h3_audio_only", "Ref2VA 音频不能作为唯一参考输入")
    if totals["video"] > 15:
        report.add("error", "h3_reference_video_total",
                   f"Ref2VA 视频参考累计 {totals['video']:.2f} 秒，最多为 15 秒")
    if totals["audio"] > 15:
        report.add("error", "h3_reference_audio_total",
                   f"Ref2VA 音频参考累计 {totals['audio']:.2f} 秒，最多为 15 秒")


def _check_unresolved_references(report, prompt: str) -> None:
    for label in re.findall(r"<([^>]+)>", prompt):
        if label in {"scenetrans", "/scenetrans", "cutoff", "/cutoff", "d", "/d"}:
            continue
        if not re.fullmatch(r"(?:Subject|Picture|Video|Audio) \d+", label):
            report.add("warning", "h3_reference_unknown", f"无法识别的引用标签 <{label}>")


def _check_plan_references(report, plan, mode: str = "Ref2VA") -> None:
    defined = {str(label).strip("<>") for label in plan.all_reference_labels()}
    used = set()
    for shot in plan.shots:
        used.update(str(label).strip("<>") for label in shot.references)
    used.update(str(item.label).strip("<>") for item in plan.retention)
    for label in sorted(used - defined):
        report.add("error", "h3_reference_undefined", f"引用 <{label}> 没有对应定义")
    # I2VA/FL2VA/L2VA consume their connected pictures through the mandatory
    # deterministic alignment line. The six-section retention_analysis contract
    # exists only in Ref2VA; demanding it in base modes made every valid I2VA plan
    # fail even though the rendered first line already fully references Picture 1.
    if mode not in {"R2V", "Ref2VA"}:
        return
    shot_used = {str(label).strip("<>") for shot in plan.shots for label in shot.references}
    retained = {str(item.label).strip("<>") for item in plan.retention}
    for label in sorted(defined - shot_used):
        report.add("error", "h3_reference_unused",
                   f"已定义的 <{label}> 未在任何具体 Shot 的 references 中生效")
    for label in sorted(defined - retained):
        report.add("error", "h3_reference_retention_missing",
                   f"已定义的 <{label}> 缺少 retention_analysis 决策")


def _check_plan_speakers(report, plan) -> None:
    defined = {speaker.speaker_id for speaker in plan.speakers}
    used = {sid for shot in plan.shots for dialogue in shot.dialogues
            for sid in dialogue.speaker_ids}
    for sid in sorted(used - defined):
        report.add("error", "h3_speaker_undefined", f"说话人 {sid} 没有定义")
    for shot in plan.shots:
        for dialogue in shot.dialogues:
            if dialogue.kind == "voiceover" and not dialogue.lips_closed:
                report.add("error", "h3_voiceover_lips",
                           "voiceover 必须设置 lips_closed=true")


# ---------------------------------------------------------------- R2V 英文

_NON_ASCII_RE = re.compile(r"[^\x00-\x7f]")


def r2v_english_issue(prompt: str) -> Optional[str]:
    """检测 R2V 语义段是否包含大量非英语内容（<d> 对白与引号内画面文字除外）。

    返回首个违规段名；都合规返回 None。不伪造翻译，只报告。
    """
    import re as _re

    semantic = ["subject_definitions", "summary", "retention_analysis",
                "detailed_description", "overall_soundscape", "non_diegetic_music"]
    for heading in semantic:
        body = _section_text(prompt, heading)
        if not body:
            continue
        # 剔除 <d>...</d>（对白/歌词保留原语言）
        body = _re.sub(r"<d>.*?</d>", "", body, flags=_re.S)
        # 剔除双引号内的画面文字（按官方规则保留原文字）
        body = _re.sub(r'"[^"]*"', "", body)
        chars = [c for c in body if not c.isspace()]
        if not chars:
            continue
        non_ascii = len([c for c in chars if _NON_ASCII_RE.match(c)])
        if non_ascii / len(chars) > 0.25:
            return heading
    return None

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


def validate_h3(prompt: str, mode: str = "T2VA") -> ValidationReport:
    report = ValidationReport()
    report.checks.append(f"h3_{mode}")
    if not prompt or not prompt.strip():
        report.add("error", "h3_empty", "提示词为空")
        return report

    # 1) 段/字段结构
    if mode == "R2V":
        _check_section_order(report, prompt, R2V_SECTION_HEADINGS, "h3_section")
        _check_r2v_style_opening(report, prompt)
        _check_retention_markers(report, prompt)
        _check_summary_prefix(report, prompt)
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
    _check_shots(report, prompt, mode)

    # 3) 标签编号
    _check_labels(report, prompt)

    # 4) 对白 <d>[Language]</d>
    _check_dialogues(report, prompt)

    # 5) 说话人 ID
    _check_speakers(report, prompt)

    # 6) 音频段内容规则
    _check_soundscape(report, prompt)
    _check_music(report, prompt, mode)
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

def _check_shots(report, prompt, mode: str) -> None:
    heading = ("integrated_multimodal_description" if mode != "R2V"
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
    markers = ["fully_preserved", "partially_preserved", "attribute_transfer",
               "weak_reference", "fully_copy", "partially_copy", "reference"]
    section = _section_text(prompt, "retention_analysis")
    for line in section.splitlines():
        if not line.strip():
            continue
        if not any(m in line for m in markers):
            report.add("warning", "h3_retention_marker",
                       f"retention_analysis 行缺少合法 marker：{line.strip()[:60]}")


def _check_summary_prefix(report, prompt) -> None:
    summary = _section_text(prompt, "summary")
    if summary and not summary.startswith("["):
        report.add("error", "h3_summary_prefix",
                   "R2V summary 必须以方括号任务类型前缀开头，如 [reference generation]")


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

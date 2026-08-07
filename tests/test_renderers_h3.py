"""H3 确定性渲染器测试（官方手册格式规则的 Python 复现）。"""
import pytest

from aps.renderers.minimax_h3 import (
    format_timestamp,
    render_dialogue,
    render_h3,
    render_shot,
)
from aps.schemas.h3 import (
    H3Asset,
    H3Dialogue,
    H3PromptPlan,
    H3Retention,
    H3Shot,
    H3Subject,
)


def make_plan(mode="T2VA", duration=10.0, n_shots=2, assets=None, **kw):
    shots = [H3Shot(index=1, description=["A girl enters the cafe."],
                    camera="The camera pans slowly.",
                    dialogues=[H3Dialogue(language="Chinese", text="你好。",
                                          speaker_ids=["S1"])]),
             H3Shot(index=2, start_time=5.0,
                    description=["She sits by the window."])]
    return H3PromptPlan(mode=mode, duration_seconds=duration,
                        shots=shots, assets=assets or [], **kw)


# ------------------------------------------------------------------ 时间戳

def test_format_timestamp_zero():
    assert format_timestamp(0) == "00:00.000"


def test_format_timestamp_seconds():
    assert format_timestamp(5.0) == "00:05.000"


def test_format_timestamp_minutes():
    assert format_timestamp(61.5) == "01:01.500"


def test_format_timestamp_millis():
    assert format_timestamp(0.25) == "00:00.250"


def test_format_timestamp_negative_clamps():
    assert format_timestamp(-3) == "00:00.000"


# ------------------------------------------------------------------ 对白

def test_render_dialogue_speech():
    d = H3Dialogue(language="English", text="Hello.", speaker_ids=["S1"])
    assert render_dialogue(d) == "(S1) says: <d>[English] Hello.</d>"


def test_render_dialogue_singing():
    d = H3Dialogue(language="Chinese", text="月亮之上", speaker_ids=["S2"], kind="singing")
    assert render_dialogue(d) == "(S2) sings: <d>[Chinese] 月亮之上</d>"


def test_render_dialogue_voiceover():
    d = H3Dialogue(language="English", text="Long ago...", speaker_ids=["S1", "S2"],
                   kind="voiceover")
    assert render_dialogue(d) == \
        "(S1,S2) says in an off-screen voiceover: <d>[English] Long ago...</d>"


# ------------------------------------------------------------------ 镜头

def test_render_shot_first_no_timestamp():
    shot = H3Shot(index=1, description=["Wide shot of the city."], camera="wide")
    out = render_shot(shot)
    assert out.startswith("[Shot 1] ")
    assert "At " not in out
    assert "Wide shot of the city." in out
    assert "wide." in out  # camera 句号收尾


def test_render_shot_with_timestamp():
    shot = H3Shot(index=2, start_time=5.25,
                  description=["Close-up on her face."])
    assert render_shot(shot) == "[Shot 2] At 00:05.250, Close-up on her face."


# ------------------------------------------------------------------ 四模式

def test_t2va_no_instruction_and_three_fields():
    plan = make_plan("T2VA")
    out = render_h3(plan)
    assert not out.startswith("How the reference pictures align")
    assert not out.startswith("For the target video")
    assert out.splitlines()[0] == ("integrated_multimodal_description: [Shot 1] "
                                   "A girl enters the cafe. The camera pans slowly. "
                                   "(S1) says: <d>[Chinese] 你好。</d> "
                                   "[Shot 2] At 00:05.000, She sits by the window.")
    assert out.splitlines()[1].startswith("overall_soundscape: ")
    assert out.splitlines()[2].startswith("non_diegetic_music: ")


def test_i2va_instruction_exact():
    plan = make_plan("I2VA", assets=[H3Asset(label="Picture 1", kind="picture",
                                             alignment_time=0.0)])
    out = render_h3(plan)
    first = out.split("\n\n")[0]
    assert first == ("For the target video, at 0.00 seconds into the target video, "
                     "<Picture 1> (from [Shot 1]) is fully referenced.")


def test_fl2va_default_single_shot_path_two_decimals():
    plan = make_plan("FL2VA", duration=10.0, n_shots=1, assets=[])
    first = render_h3(plan).split("\n\n")[0]
    assert first.startswith("How the reference pictures align with the target video — ")
    assert "0.00-second mark" in first
    assert "10.00-second mark" in first


def test_fl2va_two_assets_uses_asset_times():
    plan = make_plan("FL2VA", duration=10.0, n_shots=3,
                     assets=[H3Asset(label="Picture 1", kind="picture", source="1",
                                     alignment_time=0.0),
                             H3Asset(label="Picture 2", kind="picture", source="3",
                                     alignment_time=10.0)])
    first = render_h3(plan).split("\n\n")[0]
    assert "Picture 1 (from Shot 1) aligns with the 0.00-second mark" in first
    assert "Picture 2 (from Shot 3) aligns with the 10.00-second mark" in first


def test_l2va_instruction():
    plan = make_plan("L2VA", duration=8.0, n_shots=2)
    first = render_h3(plan).split("\n\n")[0]
    assert first.startswith("How the reference pictures align with the target video — ")
    assert "<Picture 1> (from [Shot 2]) aligns with the 8.00-second mark" in first


def test_soundscape_includes_shot_audio_notes():
    plan = make_plan("T2VA")
    plan.shots[0].audio_notes = "Rain falls on the window"
    plan.soundscape = "The cafe hums softly."
    out = render_h3(plan)
    sound = [l for l in out.splitlines() if l.startswith("overall_soundscape: ")][0]
    assert "The cafe hums softly." in sound
    assert "Rain falls on the window." in sound


# ------------------------------------------------------------------ R2V

def test_r2v_six_sections_in_order():
    plan = make_plan("R2V")
    plan.style_opening = "A quiet, painterly style with soft window light."
    plan.summary = "[reference generation] A girl enters a cafe and sits down."
    plan.subjects = [H3Subject(label="Subject 1", kind="character",
                               definition="The girl with long dark hair, "
                                          "reused from <Picture 1>.")]
    plan.assets = [H3Asset(label="Audio 1", kind="audio", note="the original soundtrack")]
    plan.retention = [H3Retention(label="Subject 1", marker="fully_preserved",
                                  notes="retained as-is", shot_refs=["Shot 1", "Shot 2"])]
    plan.soundscape = "The cafe hums softly."
    plan.non_diegetic_music = "N/A"
    out = render_h3(plan)
    lines = out.splitlines()
    headings = [i for i, l in enumerate(lines) if l in (
        "subject_definitions:", "summary:", "retention_analysis:",
        "detailed_description:", "overall_soundscape:", "non_diegetic_music:")]
    assert [lines[i] for i in headings] == [
        "subject_definitions:", "summary:", "retention_analysis:",
        "detailed_description:", "overall_soundscape:", "non_diegetic_music:"]
    # 风格开场在 [Shot 1] 之前
    dd_start = lines.index("detailed_description:")
    assert lines[dd_start + 1] == "A quiet, painterly style with soft window light."
    assert "[Shot 1]" in lines[dd_start + 2]
    # 对白语言保留
    assert "<d>[Chinese] 你好。</d>" in out

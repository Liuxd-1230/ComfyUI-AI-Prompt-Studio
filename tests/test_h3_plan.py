"""H3 计划服务测试：LLM 指令构造、JSON 容错解析、分镜转换、图片映射。"""
import json

import pytest

from aps.schemas.h3 import H3PromptPlan
from aps.schemas.references import AssetRef, ReferenceManifest, SubjectRef
from aps.schemas.storyboard import Scene, Shot, Storyboard
from aps.services.h3_plan import (
    build_plan_prompt,
    convert_storyboard,
    map_image_assets,
    parse_plan_json,
)

# ---------------------------------------------------------------- 指令构造

def test_build_plan_prompt_contains_mode_duration_and_input():
    p = build_plan_prompt("少女走进咖啡店。", "I2VA", 8.0)
    assert "[模式] I2VA" in p
    assert "8.00 秒" in p
    assert "non_diegetic_music" in p
    assert "少女走进咖啡店。" in p


def test_build_plan_prompt_reference_images_and_repair():
    p = build_plan_prompt("x", "FL2VA", 5.0, image_count=2,
                          repair_issues="[error] h3_fl2va_2dp: 两位小数")
    assert "<Picture 1..2>" in p
    assert "[需修复的校验问题]" in p
    assert "h3_fl2va_2dp" in p


def test_build_plan_prompt_with_storyboard_and_bible():
    sb = Storyboard(title="t", characters=["c1"],
                    scenes=[Scene(title="s1", shots=[Shot(summary="walk in")])])
    p = build_plan_prompt("x", "T2VA", 5.0, storyboard=sb)
    assert "[分镜]" in p
    assert "walk in" in p


# ---------------------------------------------------------------- 解析

PLAN_JSON = {
    "style_opening": "",
    "summary": "",
    "speakers": [{"speaker_id": "S1", "name": "girl"}],
    "subjects": [],
    "assets": [],
    "retention": [],
    "soundscape": "The cafe hums softly.",
    "non_diegetic_music": "A slow piano theme.",
    "shots": [
        {"index": 1, "start_time": None,
         "description": ["A girl enters the cafe."],
         "camera": "The camera pans slowly.",
         "characters": ["S1"], "audio_notes": "",
         "dialogues": [{"language": "Chinese", "text": "你好。",
                        "speaker_ids": ["S1"], "kind": "speech"}]},
        {"index": 2, "start_time": 5.0,
         "description": ["She sits down."], "camera": "",
         "characters": [], "dialogues": []},
    ],
}


def test_parse_plan_json_valid():
    plan = parse_plan_json(json.dumps(PLAN_JSON), "T2VA", 10.0)
    assert plan.mode == "T2VA"
    assert len(plan.shots) == 2
    assert plan.shots[0].start_time is None
    assert plan.shots[1].start_time == 5.0
    assert plan.shots[0].dialogues[0].text == "你好。"
    assert plan.speakers[0].speaker_id == "S1"
    assert plan.soundscape == "The cafe hums softly."


def test_parse_plan_json_tolerant_extra_fields_and_types():
    raw = '{"shots": [{"index": 1, "description": "single string not list", "camera": 5}], "soundscape": 123}'
    plan = parse_plan_json(raw, "I2VA", 10.0)
    assert len(plan.shots) == 1
    assert plan.shots[0].description == []  # 非列表 → 空
    assert plan.shots[0].camera == "5"      # 数值容错转字符串
    assert plan.soundscape == ""


def test_parse_plan_json_coerces_strictly_increasing():
    raw = ('{"shots": [{"index": 1, "start_time": null, "description": ["a"]},'
           '{"index": 2, "start_time": 3.0, "description": ["b"]},'
           '{"index": 3, "start_time": 2.0, "description": ["c"]},'
           '{"index": 4, "description": ["d"]}]}')
    plan = parse_plan_json(raw, "L2VA", 20.0)
    times = [s.start_time for s in plan.shots]
    assert times[0] is None
    assert times[1] == 3.0
    assert times[2] >= times[1] + 0.001   # 2.0 被强制拉高
    assert times[3] >= times[2] + 0.001   # 缺失 → 自动递增
    assert all(t is None or t < 20.0 for t in times)


def test_parse_plan_json_shot1_forced_no_timestamp():
    raw = '{"shots": [{"index": 1, "start_time": 7.0, "description": ["a"]}]}'
    plan = parse_plan_json(raw, "I2VA", 10.0)
    assert plan.shots[0].start_time is None


def test_parse_plan_json_auto_fill_missing_shot2():
    raw = ('{"shots": [{"index": 1, "description": ["a"]},'
           '{"index": 2, "description": ["b"]}]}')
    plan = parse_plan_json(raw, "I2VA", 10.0)
    assert plan.shots[1].start_time is not None
    assert plan.shots[1].start_time > 0


def test_parse_plan_json_bad_json():
    with pytest.raises(ValueError, match="JSON"):
        parse_plan_json("这不是 JSON", "T2VA", 10.0)


def test_parse_plan_json_clamps_marker():
    raw = '{"retention": [{"label": "Subject 1", "marker": "nope"}], "shots": []}'
    plan = parse_plan_json(raw, "R2V", 10.0)
    assert plan.retention[0].marker == "fully_preserved"


# ---------------------------------------------------------------- 分镜转换

def make_storyboard():
    return Storyboard(
        title="咖啡店", summary="少女走进咖啡店", style="Cinematic",
        characters=["c1"],
        scenes=[Scene(scene_id="s1", title="进门", characters=["c1"],
                      shots=[Shot(shot_id="s1sh1", summary="推门全景",
                                  action="少女推门", camera="wide shot",
                                  duration=3.0, characters=["c1"]),
                             Shot(shot_id="s1sh2", summary="落座特写",
                                  action="少女坐下", camera="close-up",
                                  duration=7.0, characters=["c1"])])])


def make_manifest():
    return ReferenceManifest(
        assets=[AssetRef(asset_id="img1", asset_type="image",
                         path_or_ref="E:/refs/girl.png", h3_labels=["Picture 1"])],
        subjects=[SubjectRef(subject_id="Subject 1", kind="character",
                             definition="the girl from the reference image",
                             source_assets=["img1"])])


def test_convert_storyboard_maps_structure():
    sb = make_storyboard()
    plan = convert_storyboard(sb, "T2VA", 10.0, manifest=make_manifest())
    assert plan.mode == "T2VA"
    assert plan.storyboard_id == sb.story_id
    assert len(plan.shots) == 2
    assert plan.shots[0].start_time is None
    assert plan.shots[1].start_time == 5.0   # 10s / 2 镜头
    assert plan.shots[0].description[0] == "推门全景"
    assert [s.speaker_id for s in plan.speakers] == ["S1"]
    assert plan.speakers[0].character_id == "c1"
    assert plan.subjects[0].label == "Subject 1"
    assert plan.assets[0].label == "Picture 1"
    assert plan.assets[0].kind == "picture"
    assert plan.retention[0].marker == "fully_preserved"
    assert plan.summary.startswith("[reference generation]")
    assert plan.style_opening == "Cinematic"


def test_convert_storyboard_audio_asset_kind():
    sb = make_storyboard()
    manifest = ReferenceManifest(
        assets=[AssetRef(asset_id="a1", asset_type="audio", path_or_ref="bgm.wav")])
    plan = convert_storyboard(sb, "R2V", 10.0, manifest=manifest)
    assert plan.assets[0].kind == "audio"
    assert plan.assets[0].label == "Audio 1"


# ---------------------------------------------------------------- 图片映射

def test_map_image_assets_i2va():
    plan = H3PromptPlan(mode="I2VA", duration_seconds=8.0)
    map_image_assets(plan, 1, "I2VA")
    assert plan.assets[0].label == "Picture 1"
    assert plan.assets[0].alignment_time == 0.0


def test_map_image_assets_fl2va_first_last():
    plan = H3PromptPlan(mode="FL2VA", duration_seconds=8.0, shots=[object()])
    map_image_assets(plan, 2, "FL2VA")
    assert plan.assets[0].label == "Picture 1"
    assert plan.assets[0].alignment_time == 0.0
    assert plan.assets[1].label == "Picture 2"
    assert plan.assets[1].alignment_time == 8.0


def test_map_image_assets_l2va_last_frame():
    plan = H3PromptPlan(mode="L2VA", duration_seconds=8.0, shots=[object()])
    map_image_assets(plan, 1, "L2VA")
    assert plan.assets[0].alignment_time == 8.0


def test_map_image_assets_skips_existing():
    plan = H3PromptPlan(mode="I2VA", duration_seconds=8.0)
    from aps.schemas.h3 import H3Asset

    plan.assets.append(H3Asset(label="Picture 1", kind="picture", source="1",
                               alignment_time=0.0))
    map_image_assets(plan, 1, "I2VA")
    assert len(plan.assets) == 1


# ---------------------------------------------------------------- 媒体独立编号

def test_normalize_media_labels_per_kind():
    from aps.schemas.h3 import H3Asset, H3Retention
    from aps.services.h3_plan import normalize_media_labels

    plan = H3PromptPlan(mode="R2V", duration_seconds=10.0)
    plan.assets = [
        H3Asset(label="Picture 1", kind="picture"),
        H3Asset(label="Video 2", kind="video"),
        H3Asset(label="Audio 3", kind="audio"),
        H3Asset(label="Video 5", kind="video"),
        H3Asset(label="Picture 4", kind="picture"),
    ]
    plan.retention = [H3Retention(label="Video 5", marker="fully_copy", notes="x"),
                      H3Retention(label="Picture 4", marker="fully_preserved", notes="y")]
    normalize_media_labels(plan)
    labels = [a.label for a in plan.assets]
    assert labels == ["Picture 1", "Video 1", "Audio 1", "Video 2", "Picture 2"]
    # retention 引用同步改写
    assert plan.retention[0].label == "Video 2"
    assert plan.retention[1].label == "Picture 2"


def test_map_image_assets_mode_constraints_warnings():
    from aps.services.h3_plan import map_image_assets

    plan = H3PromptPlan(mode="I2VA", duration_seconds=8.0)
    warnings = map_image_assets(plan, 0, "I2VA")
    assert any("I2VA" in w for w in warnings)
    plan2 = H3PromptPlan(mode="FL2VA", duration_seconds=8.0)
    warnings2 = map_image_assets(plan2, 1, "FL2VA")
    assert any("FL2VA" in w for w in warnings2)
    plan3 = H3PromptPlan(mode="T2VA", duration_seconds=8.0)
    warnings3 = map_image_assets(plan3, 2, "T2VA")
    assert any("T2VA" in w for w in warnings3)

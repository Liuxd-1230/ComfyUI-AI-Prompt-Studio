"""H3 校验器测试：每条官方规则的正反用例（格式由我按手册规则构造，非手册原文复制）。"""
from aps.schemas.h3 import H3Asset, H3Dialogue, H3PromptPlan, H3Retention, H3Shot
from aps.schemas.references import AssetRef, ReferenceManifest
from aps.validators.minimax_h3 import validate_h3

# ---------------------------------------------------------------- 合法样例

FOUR_MODE_OK = (
    "For the target video, at 0.00 seconds into the target video, "
    "<Picture 1> (from [Shot 1]) is fully referenced.\n\n"
    "integrated_multimodal_description: [Shot 1] A girl enters the cafe. "
    "(S1) says: <d>[Chinese] 你好。</d> [Shot 2] At 00:05.000, She sits down.\n"
    "overall_soundscape: The cafe hums softly.\n"
    "non_diegetic_music: A slow piano theme in D minor."
)

R2V_OK = (
    "subject_definitions:\n"
    "<Subject 1> is the girl with long dark hair, reused from <Picture 1>.\n"
    "<Audio 1> is the original dialogue track.\n"
    "summary:\n"
    "[reference generation] A girl enters a cafe and sits by the window.\n"
    "retention_analysis:\n"
    "<Subject 1> (appears in [Shot 1], [Shot 2]): fully_preserved - retained as-is\n"
    "<Audio 1>: fully_copy - keep the original track\n"
    "detailed_description:\n"
    "A quiet painterly style with soft window light.\n"
    "[Shot 1] The girl walks in.\n"
    "[Shot 2] At 00:06.000, She sits down.\n"
    "overall_soundscape:\n"
    "The cafe hums softly.\n"
    "non_diegetic_music:\n"
    "N/A"
)


def test_four_mode_ok():
    assert validate_h3(FOUR_MODE_OK, "I2VA").valid is True


def test_r2v_ok():
    assert validate_h3(R2V_OK, "R2V").valid is True


def test_plan_rejects_undefined_reference_and_speaker():
    plan = H3PromptPlan(mode="Ref2VA", shots=[H3Shot(
        references=["Picture 99"], dialogues=[H3Dialogue(
            text="hello", speaker_ids=["S9"])])])
    report = validate_h3(R2V_OK, "Ref2VA", plan=plan)
    codes = {issue.code for issue in report.issues}
    assert "h3_reference_undefined" in codes
    assert "h3_speaker_undefined" in codes


def test_ref2va_duration_outside_official_range_fails():
    report = validate_h3(R2V_OK, "Ref2VA", duration=16)
    assert any(issue.code == "h3_duration" for issue in report.issues)


def test_ref2va_rejects_defined_asset_not_used_in_shot_or_retention():
    plan = H3PromptPlan(mode="Ref2VA", assets=[H3Asset(label="Picture 1")],
                        shots=[H3Shot(index=1)])
    report = validate_h3(R2V_OK, "Ref2VA", plan=plan)
    codes = {issue.code for issue in report.issues}
    assert "h3_reference_unused" in codes
    assert "h3_reference_retention_missing" in codes


def test_ref2va_accepts_asset_used_at_exact_shot_and_retained():
    plan = H3PromptPlan(
        mode="Ref2VA", assets=[H3Asset(label="Picture 1")],
        retention=[H3Retention(label="Picture 1", marker="fully_preserved")],
        shots=[H3Shot(index=1, references=["Picture 1"])])
    report = validate_h3(R2V_OK, "Ref2VA", plan=plan)
    codes = {issue.code for issue in report.issues}
    assert "h3_reference_unused" not in codes
    assert "h3_reference_retention_missing" not in codes


def test_ref2va_rejects_unknown_and_excess_total_media_duration():
    manifest = ReferenceManifest(assets=[
        AssetRef(asset_id="v1", asset_type="video", time_start=0, time_end=10),
        AssetRef(asset_id="v2", asset_type="video", time_start=0, time_end=10),
        AssetRef(asset_id="a1", asset_type="audio"),
        AssetRef(asset_id="p1", asset_type="image"),
    ])
    report = validate_h3(R2V_OK, "Ref2VA", manifest=manifest)
    codes = {issue.code for issue in report.issues}
    assert "h3_reference_video_total" in codes
    assert "h3_reference_duration_unknown" in codes


def test_ref2va_rejects_retention_marker_for_wrong_modality():
    prompt = R2V_OK.replace("<Subject 1> (appears in [Shot 1], [Shot 2]): fully_preserved",
                            "<Subject 1>: fully_copy")
    report = validate_h3(prompt, "Ref2VA")
    assert any(issue.code == "h3_retention_modality" for issue in report.issues)


# ---------------------------------------------------------------- 结构

def test_empty_prompt():
    r = validate_h3("", "T2VA")
    assert not r.valid
    assert any(i.code == "h3_empty" for i in r.issues)


def test_missing_field():
    prompt = ("[Shot 1] A girl enters the cafe.\n"
              "overall_soundscape: The cafe hums softly.\n"
              "non_diegetic_music: N/A")
    r = validate_h3(prompt, "T2VA")
    assert any(i.code == "h3_field_missing" for i in r.issues)


def test_field_order():
    prompt = ("non_diegetic_music: N/A\n"
              "integrated_multimodal_description: [Shot 1] A girl enters.\n"
              "overall_soundscape: The cafe hums softly.")
    r = validate_h3(prompt, "T2VA")
    assert any(i.code == "h3_field_order" for i in r.issues)


def test_r2v_section_missing():
    prompt = R2V_OK.replace("retention_analysis:\n<Subject 1> (appears in [Shot 1], [Shot 2]): fully_preserved - retained as-is\n<Audio 1>: fully_copy - keep the original track\n", "")
    r = validate_h3(prompt, "R2V")
    assert any(i.code == "h3_section_missing" for i in r.issues)
    assert any(i.code == "h3_section_incomplete" for i in r.issues)


# ---------------------------------------------------------------- 首行对齐指令

def test_i2va_wrong_instruction():
    prompt = FOUR_MODE_OK.replace(
        "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.",
        "A nice video starts with a picture.")
    r = validate_h3(prompt, "I2VA")
    assert any(i.code == "h3_i2va_instruction" for i in r.issues)


def test_t2va_with_instruction_forbidden():
    r = validate_h3(FOUR_MODE_OK, "T2VA")
    assert any(i.code == "h3_instruction_unexpected" for i in r.issues)


def test_fl2va_one_decimal_mark():
    prompt = FOUR_MODE_OK.replace(
        "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.",
        "How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 2) aligns with the 8.0-second mark of the target video.")
    r = validate_h3(prompt, "FL2VA")
    assert any(i.code == "h3_fl2va_2dp" for i in r.issues)


def test_fl2va_missing_prefix():
    prompt = FOUR_MODE_OK.replace(
        "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.",
        "The reference pictures align with the video.")
    r = validate_h3(prompt, "FL2VA")
    assert any(i.code == "h3_fl2va_instruction" for i in r.issues)


def test_l2va_missing_picture():
    prompt = FOUR_MODE_OK.replace(
        "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.",
        "How the reference pictures align with the target video — the final frame.")
    r = validate_h3(prompt, "L2VA")
    assert any(i.code == "h3_l2va_picture" for i in r.issues)


# ---------------------------------------------------------------- 镜头

def test_no_shots():
    r = validate_h3("integrated_multimodal_description: nothing here.\n"
                    "overall_soundscape: quiet.\nnon_diegetic_music: N/A", "T2VA")
    assert any(i.code == "h3_no_shots" for i in r.issues)


def test_shot1_must_not_have_timestamp():
    prompt = FOUR_MODE_OK.replace("[Shot 1] A girl enters the cafe.",
                                  "[Shot 1] At 00:00.000, A girl enters the cafe.")
    r = validate_h3(prompt, "I2VA")
    assert any(i.code == "h3_shot1_timestamp" for i in r.issues)


def test_shot_numbering_gap():
    prompt = FOUR_MODE_OK.replace("[Shot 2] At 00:05.000,", "[Shot 3] At 00:05.000,")
    r = validate_h3(prompt, "I2VA")
    assert any(i.code == "h3_shot_numbering" for i in r.issues)


def test_shot_missing_timestamp():
    prompt = FOUR_MODE_OK.replace("[Shot 2] At 00:05.000,", "[Shot 2]")
    r = validate_h3(prompt, "I2VA")
    assert any(i.code == "h3_shot_missing_ts" for i in r.issues)


def test_shot_timestamp_format():
    prompt = ("integrated_multimodal_description: [Shot 1] A.\n"
              "[Shot 2] At 00:05:000, B.\n"
              "overall_soundscape: quiet.\n"
              "non_diegetic_music: N/A")
    r = validate_h3(prompt, "T2VA")
    assert any(i.code == "h3_ts_format" for i in r.issues)


def test_shot_timestamp_not_increasing():
    prompt = ("integrated_multimodal_description: [Shot 1] A.\n"
              "[Shot 2] At 00:05.000, B.\n"
              "[Shot 3] At 00:03.000, C.\n"
              "overall_soundscape: quiet.\n"
              "non_diegetic_music: N/A")
    r = validate_h3(prompt, "T2VA")
    assert any(i.code == "h3_ts_increasing" for i in r.issues)


def test_shot1_timestamp_in_r2v():
    prompt = R2V_OK.replace("[Shot 1] The girl walks in.",
                            "[Shot 1] At 00:00.000, The girl walks in.")
    r = validate_h3(prompt, "R2V")
    assert any(i.code == "h3_shot1_timestamp" for i in r.issues)


# ---------------------------------------------------------------- 标签

def test_label_numbering_gap():
    prompt = FOUR_MODE_OK.replace("<Picture 1> (from [Shot 1])",
                                  "<Picture 2> (from [Shot 1])")
    r = validate_h3(prompt, "I2VA")
    assert any(i.code == "h3_label_numbering" for i in r.issues)


# ---------------------------------------------------------------- 对白

def test_dialogue_unbalanced():
    prompt = FOUR_MODE_OK.replace("</d>", "")
    r = validate_h3(prompt, "I2VA")
    assert any(i.code == "h3_dialogue_unbalanced" for i in r.issues)


def test_dialogue_missing_language():
    prompt = FOUR_MODE_OK.replace("<d>[Chinese] 你好。</d>", "<d> 你好。</d>")
    r = validate_h3(prompt, "I2VA")
    assert any(i.code == "h3_dialogue_language" for i in r.issues)


# ---------------------------------------------------------------- 音频段内容

def test_soundscape_repeats_dialogue():
    prompt = FOUR_MODE_OK.replace(
        "overall_soundscape: The cafe hums softly.",
        "overall_soundscape: (S1) says: <d>[Chinese] 你好。</d>")
    r = validate_h3(prompt, "I2VA")
    assert any(i.code == "h3_soundscape_dialogue" for i in r.issues)


def test_music_abstract_word():
    prompt = FOUR_MODE_OK.replace("A slow piano theme in D minor.",
                                  "A sad and emotional mood.")
    r = validate_h3(prompt, "I2VA")
    assert any(i.code == "h3_music_abstract" for i in r.issues)


def test_music_duplicates_soundscape():
    prompt = FOUR_MODE_OK.replace("non_diegetic_music: A slow piano theme in D minor.",
                                  "non_diegetic_music: The cafe hums softly.")
    r = validate_h3(prompt, "I2VA")
    assert any(i.code == "h3_audio_duplicate" for i in r.issues)


# ---------------------------------------------------------------- R2V 特有

def test_r2v_summary_prefix():
    prompt = R2V_OK.replace("[reference generation] A girl enters a cafe and sits by the window.",
                            "A girl enters a cafe and sits by the window.")
    r = validate_h3(prompt, "R2V")
    assert any(i.code == "h3_summary_prefix" for i in r.issues)


def test_r2v_retention_marker():
    prompt = R2V_OK.replace("fully_preserved - retained as-is", "kept the same look")
    r = validate_h3(prompt, "R2V")
    assert any(i.code == "h3_retention_marker" for i in r.issues)


def test_ref2va_rejects_generic_asset_labels_and_malformed_retention() -> None:
    prompt = R2V_OK.replace("<Picture 1>", "<Asset 1>")

    report = validate_h3(prompt, "Ref2VA")

    assert not report.valid
    assert any(issue.code == "h3_reference_unknown" and issue.severity == "error"
               for issue in report.issues)


def test_ref2va_rejects_retention_text_between_label_and_colon() -> None:
    prompt = R2V_OK.replace(
        "<Picture 1>: fully_preserved",
        "<Picture 1> (appears in [Shot 1]): fully_preserved")

    report = validate_h3(prompt, "Ref2VA")

    assert not report.valid
    assert any(issue.code == "h3_retention_marker" and issue.severity == "error"
               for issue in report.issues)


def test_ref2va_unanalysed_picture_cannot_claim_full_preservation() -> None:
    from aps.schemas.references import AssetRef, ReferenceManifest

    manifest = ReferenceManifest(assets=[AssetRef(
        asset_id="image_1", asset_type="image", h3_labels=["Picture 1"],
        note="unanalysed connected picture reference; contents unavailable")])

    prompt = R2V_OK.replace(
        "<Audio 1>: fully_copy - keep the original track",
        "<Picture 1>: fully_preserved - preserves the dancer pose\n"
        "<Audio 1>: fully_copy - keep the original track")
    report = validate_h3(prompt, "Ref2VA", manifest=manifest)

    assert not report.valid
    assert any(issue.code == "h3_unanalysed_reference_claim"
               for issue in report.issues)




def test_xml_style_closing_reference_tags_are_not_unknown_labels() -> None:
    prompt = FOUR_MODE_OK + "\n</Subject 1> </Picture 1>"

    report = validate_h3(prompt, "T2VA", duration=10.0)

    assert not any(issue.code == "h3_reference_unknown"
                   for issue in report.issues)


def test_r2v_style_opening_warning():
    prompt = R2V_OK.replace("A quiet painterly style with soft window light.\n", "")
    r = validate_h3(prompt, "R2V")
    assert any(i.code == "h3_r2v_style_opening" for i in r.issues)

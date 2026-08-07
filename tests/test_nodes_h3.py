"""节点层测试：MiniMax H3 Prompt Director（LLM mock + 确定性渲染 + 校验接线）。"""
import json

import pytest

import aps.nodes.minimax_h3_director as h3_mod
from aps.schemas.h3 import H3PromptPlan
from aps.schemas.results import LLMResult
from aps.schemas.storyboard import Scene, Shot, Storyboard


def setup_profile(store):
    store.create_profile({"profile_id": "p1", "name": "DeepSeek"})
    store.set_api_key("p1", "sk-abcdef1234567890")
    return store.get_profile("p1").node_payload()


class FakeGateway:
    """记录请求并返回预设文本。"""

    last_req = None

    def __init__(self, text):
        self.text = text

    def generate(self, profile, api_key, req):
        FakeGateway.last_req = req
        return LLMResult(text=self.text)


PLAN_JSON = {
    "style_opening": "",
    "summary": "",
    "speakers": [{"speaker_id": "S1", "name": "girl",
                  "description": "a young woman with long dark hair"}],
    "subjects": [],
    "assets": [],
    "retention": [],
    "soundscape": "The cafe hums softly.",
    "non_diegetic_music": "A slow piano theme in D minor.",
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

R2V_PLAN_JSON = {
    "style_opening": "A quiet painterly style with soft window light.",
    "summary": "[reference generation] A girl enters a cafe.",
    "speakers": [],
    "subjects": [{"label": "Subject 1", "kind": "character",
                  "definition": "the girl from <Picture 1>"}],
    "assets": [{"label": "Picture 1", "kind": "picture", "source": "1",
                "alignment_time": 0.0}],
    "retention": [{"label": "Subject 1", "marker": "fully_preserved",
                   "notes": "retained as-is", "shot_refs": ["Shot 1"]}],
    "soundscape": "The cafe hums softly.",
    "non_diegetic_music": "N/A",
    "shots": [{"index": 1, "start_time": None,
               "description": ["The girl walks in."], "camera": "",
               "characters": [], "dialogues": []}],
}


class FakeImages:
    def __init__(self, n):
        self.shape = (n, 512, 512, 3)


def node_payload(**kw):
    data = dict(AI_PROFILE=None, text="", mode="T2VA", operation="generate",
                duration=10.0, storyboard=None, character_bible=None,
                reference_manifest=None, images=None)
    data.update(kw)
    return data


def test_generate_t2va_full_chain(monkeypatch, store):
    payload = setup_profile(store)
    monkeypatch.setattr(h3_mod, "Gateway",
                        lambda: FakeGateway(json.dumps(PLAN_JSON)))
    node = h3_mod.APS_MiniMaxH3Director()
    out = node.direct(**node_payload(AI_PROFILE=payload, text="少女走进咖啡店",
                                     mode="T2VA", duration=10.0))
    prompt, plan_json, manifest_json, validation, warnings = out
    lines = prompt.splitlines()
    assert lines[0].startswith("integrated_multimodal_description: [Shot 1] ")
    assert "[Shot 2] At 00:05.000," in prompt
    assert "(S1) says: <d>[Chinese] 你好。</d>" in prompt
    assert "overall_soundscape: The cafe hums softly." in prompt
    plan = H3PromptPlan.from_json(plan_json)
    assert plan.mode == "T2VA"
    assert len(plan.shots) == 2
    assert plan.validation.valid is True
    assert "通过" in validation
    assert warnings == ""
    assert manifest_json["assets"] == [] and manifest_json["subjects"] == []


def test_generate_i2va_with_image_adds_instruction(monkeypatch, store):
    payload = setup_profile(store)
    monkeypatch.setattr(h3_mod, "Gateway",
                        lambda: FakeGateway(json.dumps(PLAN_JSON)))
    node = h3_mod.APS_MiniMaxH3Director()
    prompt, plan_json, _, validation, _ = node.direct(
        **node_payload(AI_PROFILE=payload, text="少女走进咖啡店", mode="I2VA",
                       duration=10.0, images=FakeImages(1)))
    assert prompt.startswith(
        "For the target video, at 0.00 seconds into the target video, "
        "<Picture 1> (from [Shot 1]) is fully referenced.")
    assert "<Picture 1>" in prompt
    plan = H3PromptPlan.from_json(plan_json)
    assert any(a.label == "Picture 1" for a in plan.assets)
    assert "通过" in validation


def test_generate_r2v_full_sections(monkeypatch, store):
    payload = setup_profile(store)
    monkeypatch.setattr(h3_mod, "Gateway",
                        lambda: FakeGateway(json.dumps(R2V_PLAN_JSON)))
    node = h3_mod.APS_MiniMaxH3Director()
    prompt, plan_json, _, validation, _ = node.direct(
        **node_payload(AI_PROFILE=payload, text="少女走进咖啡店", mode="R2V",
                       duration=10.0))
    for h in ("subject_definitions:", "summary:", "retention_analysis:",
              "detailed_description:", "overall_soundscape:",
              "non_diegetic_music:"):
        assert h in prompt
    assert prompt.index("subject_definitions:") < prompt.index("summary:")
    assert "<Subject 1>" in prompt
    assert "fully_preserved" in prompt
    assert "通过" in validation


def test_generate_raises_when_empty_text(store):
    payload = setup_profile(store)
    node = h3_mod.APS_MiniMaxH3Director()
    with pytest.raises(ValueError, match="为空"):
        node.direct(**node_payload(AI_PROFILE=payload, text="", mode="T2VA",
                                   operation="generate"))


def test_audit_no_llm(monkeypatch, store):
    payload = setup_profile(store)
    captured = []
    monkeypatch.setattr(h3_mod, "Gateway", lambda: captured.append(1) or FakeGateway(""))
    node = h3_mod.APS_MiniMaxH3Director()
    good = ("[Shot 1] A girl enters the cafe.\n"
            "overall_soundscape: The cafe hums softly.\n"
            "non_diegetic_music: N/A")
    prompt, plan_json, _, validation, _ = node.direct(
        **node_payload(AI_PROFILE=payload, text=good, mode="T2VA",
                       operation="audit"))
    assert prompt == good
    assert captured == []           # audit 不调用 LLM
    plan = H3PromptPlan.from_json(plan_json)
    assert plan.operation == "audit"
    assert "通过" in validation


def test_audit_reports_issues(store):
    payload = setup_profile(store)
    node = h3_mod.APS_MiniMaxH3Director()
    bad = ("integrated_multimodal_description: [Shot 2] At 00:05.000, A girl enters.\n"
           "non_diegetic_music: N/A\n"
           "overall_soundscape: quiet")
    _, _, _, validation, _ = node.direct(
        **node_payload(AI_PROFILE=payload, text=bad, mode="T2VA",
                       operation="audit"))
    assert "h3_shot_numbering" in validation
    assert "h3_field_order" in validation


def test_repair_includes_issues_in_llm_prompt(monkeypatch, store):
    payload = setup_profile(store)
    monkeypatch.setattr(h3_mod, "Gateway",
                        lambda: FakeGateway(json.dumps(PLAN_JSON)))
    node = h3_mod.APS_MiniMaxH3Director()
    broken = ("[Shot 1] A girl enters the cafe.\n"
              "overall_soundscape: The cafe hums softly.\n"
              "non_diegetic_music: N/A")
    node.direct(**node_payload(AI_PROFILE=payload, text=broken, mode="T2VA",
                               operation="repair"))
    assert FakeGateway.last_req is not None
    sent = FakeGateway.last_req.messages[0].content
    assert "[需修复的校验问题]" in sent


def test_convert_storyboard_uses_storyboard_structure(monkeypatch, store):
    payload = setup_profile(store)
    sb = Storyboard(title="t", characters=["c1"],
                    scenes=[Scene(title="s1", characters=["c1"],
                                  shots=[Shot(summary="walk in")])])
    monkeypatch.setattr(h3_mod, "Gateway",
                        lambda: FakeGateway(json.dumps(PLAN_JSON)))
    node = h3_mod.APS_MiniMaxH3Director()
    prompt, plan_json, _, validation, _ = node.direct(
        **node_payload(AI_PROFILE=payload, text="分镜文本", mode="T2VA",
                       operation="convert_storyboard", duration=5.0,
                       storyboard=sb.to_json()))
    plan = H3PromptPlan.from_json(plan_json)
    assert plan.storyboard_id == sb.story_id
    assert "通过" in validation


def test_convert_storyboard_requires_storyboard(store):
    payload = setup_profile(store)
    node = h3_mod.APS_MiniMaxH3Director()
    with pytest.raises(ValueError, match="STORYBOARD"):
        node.direct(**node_payload(AI_PROFILE=payload, text="x",
                                   operation="convert_storyboard"))


def test_convert_storyboard_fallback_on_bad_llm(monkeypatch, store):
    payload = setup_profile(store)
    sb = Storyboard(title="t", characters=["c1"],
                    scenes=[Scene(title="s1", characters=["c1"],
                                  shots=[Shot(summary="walk in")])])
    monkeypatch.setattr(h3_mod, "Gateway", lambda: FakeGateway("不是 JSON"))
    node = h3_mod.APS_MiniMaxH3Director()
    prompt, plan_json, _, validation, warnings = node.direct(
        **node_payload(AI_PROFILE=payload, text="分镜文本", mode="T2VA",
                       operation="convert_storyboard", duration=5.0,
                       storyboard=sb.to_json()))
    plan = H3PromptPlan.from_json(plan_json)
    assert len(plan.shots) == 1
    assert "回退" in warnings


def test_no_profile():
    node = h3_mod.APS_MiniMaxH3Director()
    with pytest.raises(ValueError, match="AI_PROFILE"):
        node.direct(**node_payload(AI_PROFILE=None, text="x", mode="T2VA"))


def test_missing_api_key(store):
    store.create_profile({"profile_id": "p2", "name": "NoKey"})
    payload = store.get_profile("p2").node_payload()
    node = h3_mod.APS_MiniMaxH3Director()
    with pytest.raises(ValueError, match="API Key"):
        node.direct(**node_payload(AI_PROFILE=payload, text="x", mode="T2VA"))

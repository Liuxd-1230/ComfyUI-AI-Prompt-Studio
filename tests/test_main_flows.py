"""主线路径测试（0.2.1 §十八）：覆盖完整用户链路的 8 个 Flow。

用 mock Gateway / mock 视觉，跑真实节点 compose/build/direct/generate：
- Flow 1: Profile → LLM Generate（custom system prompt + 文本附件）
- Flow 2: Reference Analyzer → Character Bible → ANIMA Natural（稳定特征进最终 prompt）
- Flow 3: Book 双人物 → Storyboard → ANIMA Natural（Speaker ID 唯一、属性绑定正确）
- Flow 4/5/6: Book → Storyboard → Prompt Composer generic_image / sdxl / flux（必须成功）
- Flow 7: Book → Storyboard → Reference Manifest → H3 Director（编号/时间戳/媒体独立编号）
- Flow 8: 无 API Key 离线 Audit（ANIMA audit + H3 audit 必须成功）
"""
import json

import numpy as np
import pytest

import aps.nodes.character_bible as cb_mod
import aps.nodes.llm_chat as llm_mod
import aps.nodes.minimax_h3_director as h3_mod
import aps.nodes.prompt_composer as pc_mod
import aps.nodes.reference_analyzer as ra_mod
import aps.nodes.storyboard_builder as sb_mod
from aps.schemas.character import CharacterBible, CharacterBook
from aps.schemas.h3 import H3PromptPlan
from aps.schemas.prompt_plan import PromptPlan
from aps.schemas.results import LLMResult
from aps.schemas.storyboard import Scene, Shot, Storyboard


def make_profile(store, **kw):
    data = {"profile_id": "p1", "name": "DeepSeek",
            "vision_base_url": "http://v:8000/v1", "vision_model": "qwen-vl-max"}
    data.update(kw)
    store.create_profile(data)
    store.set_api_key("p1", "sk-abcdef1234567890")
    return store.get_profile("p1").node_payload()


class FakeGateway:
    def __init__(self, text):
        self.text = text
        self.last_req = None

    def generate(self, profile, api_key, req):
        self.last_req = req
        return LLMResult(text=self.text)


def plan_json(text="1girl, long hair, red dress"):
    return json.dumps({
        "normal_form_version": "2.0",
        "characters": [],
        "scene_description": text,
        "environment": [], "style": [], "composition": "", "lighting": "",
        "negative_constraints": [],
    })


def two_char_book():
    """char_01(A: 黑短发/白色军装) + char_02(B: 金长发/黑色礼服)，绑定各自属性。"""
    a = CharacterBible(character_id="char_01", name="A")
    a.traits.append(_t("hair", "black short hair", "stable"))
    a.traits.append(_t("clothing", "white military uniform", "variable"))
    b = CharacterBible(character_id="char_02", name="B")
    b.traits.append(_t("hair", "long blonde hair", "stable"))
    b.traits.append(_t("clothing", "black dress", "variable"))
    book = CharacterBook()
    book.upsert_character(a)
    book.upsert_character(b)
    book.assign_speaker_ids()
    return book


def _t(name, value, category):
    from aps.schemas.character import CharacterTrait
    return CharacterTrait(name=name, value=value, category=category,
                          confidence=0.9, locked=True)


# ================================================================ Flow 1：普通 LLM

def test_flow1_llm_generate_custom_system_and_text_attachment(monkeypatch, store, tmp_path):
    payload = make_profile(store)
    doc = tmp_path / "note.txt"
    doc.write_text("附件数据内容", encoding="utf-8")
    gw = FakeGateway("模型回答")
    monkeypatch.setattr(llm_mod, "Gateway", lambda: gw)
    from aps.services import attachments as att_svc
    monkeypatch.setattr(att_svc, "default_input_dir", lambda: str(tmp_path))
    # 直接给 ATTACHMENT_LIST（避免依赖文件路径注入）
    from aps.schemas.attachments import Attachment, AttachmentList
    att_list = AttachmentList(attachments=[
        Attachment.from_text("附件数据内容", name="note.txt")])
    node = llm_mod.APS_LLMGenerate()
    text, reasoning, sess_json, result_json, _, _, warnings = node.generate(
        AI_PROFILE=payload, system_prompt="You are a careful reviewer.",
        user_prompt="请总结", context="",
        session=None, history_mode="append", output_mode="text", json_schema="",
        attachments=json.dumps(att_list.to_json()))
    assert text == "模型回答"
    assert gw.last_req is not None
    # 用户 system_prompt 作为真实 system 指令合并发送（内部守则在前面，未丢弃）
    assert "You are a careful reviewer." in gw.last_req.system
    assert "ComfyUI" in gw.last_req.system
    # 文本附件进入请求（能力门槛：文本任何协议可用）
    assert gw.last_req.attachments and gw.last_req.attachments[0].content == "附件数据内容"
    sess = sess_json if isinstance(sess_json, dict) else json.loads(sess_json)
    assert sess["messages"][-1]["role"] == "assistant"


# ================================================================ Flow 2：单人物 ANIMA Natural

def test_flow2_reference_to_bible_to_anima_natural(monkeypatch, store):
    payload = make_profile(store)

    class FakeGateway2:
        def generate(self, profile, api_key, req):
            return LLMResult(text=json.dumps({"name": "少女", "traits": [
                {"name": "hair", "value": "long black hair", "category": "stable",
                 "confidence": 0.9}]}))

    monkeypatch.setattr(ra_mod, "Gateway", lambda: FakeGateway2())
    monkeypatch.setattr(ra_mod.vision_svc, "call_vision",
                        lambda *a, **k: {"ok": True, "text": json.dumps({
                            "name": "少女", "traits": [
                                {"name": "hair", "value": "long black hair",
                                 "category": "stable", "confidence": 0.9}]}),
                            "raw": "raw"})
    # Reference Analyzer（文字锚点 + 1 张图）→ 候选
    ra = ra_mod.APS_ReferenceAnalyzer()
    _, cand_json, _, _, _, _, _ = ra.analyze(
        AI_PROFILE=payload, analysis_mode="character_full",
        text_anchor="长发少女", images=[np.random.rand(8, 8, 3).astype(np.float32)],
        character_bible=None, custom_prompt="")

    # 候选 → Character Bible 节点（merge 签名：merge_strategy + character_candidate，无 AI_PROFILE）
    cb = cb_mod.APS_CharacterBible()
    bible_json, _, _, _, _, _, _ = cb.merge(merge_strategy="text_priority",
                                             character_candidate=cand_json)
    bible = CharacterBible.from_json(bible_json)
    assert any(t.value == "long black hair" for t in bible.traits)

    # Bible → Prompt Composer ANIMA Natural
    gw = FakeGateway(plan_json("A girl sits by the window."))
    monkeypatch.setattr(pc_mod, "Gateway", lambda: gw)
    comp = pc_mod.APS_PromptComposer()
    created = comp.compose(
        AI_PROFILE=payload, text="少女坐在窗边", target="anima_base",
        operation="generate", prompt_mode="natural_language", negative="",
        safety_tag="none", character_bible=bible_json)
    positive, _, plan_json_out, _, _ = created
    # 稳定特征出现在最终 prompt（自然语言，非 tag soup）
    assert "long black hair" in positive
    assert positive.startswith("masterpiece, best quality, score_7, ")
    assert "safe" not in positive      # safety_tag=none 不注入安全标签
    session = json.loads(created["ui"]["prompt_session"][0])
    content = session["current_plan"]["model_plan"]["content"]
    assert content["normal_form_version"] == "2.0"
    assert "scene_description" in content
    assert "natural_body" not in content


def test_composer_rejects_anima_plan_with_duplicate_fact_owners(monkeypatch, store):
    payload = make_profile(store)
    duplicate_plan = json.dumps({
        "normal_form_version": "2.0",
        "characters": [{
            "character_id": "c1", "name": "Alice",
            "required_traits": [], "variable_traits": ["red coat"],
            "action": "", "position": "",
        }],
        "scene_description": "Alice in a red coat waits at the station.",
        "environment": [], "style": [], "composition": "", "lighting": "",
        "negative_constraints": [],
    })
    monkeypatch.setattr(pc_mod, "Gateway", lambda: FakeGateway(duplicate_plan))

    with pytest.raises(ValueError, match="未通过"):
        pc_mod.APS_PromptComposer().compose(
            AI_PROFILE=payload, text="Alice waits", target="anima_base",
            operation="generate", prompt_mode="natural_language", negative="",
            safety_tag="none")


# ================================================================ Flow 3：多人物 → Storyboard → ANIMA

def test_flow3_multi_character_book_storyboard_anima(monkeypatch, store):
    payload = make_profile(store)
    book = two_char_book()
    sids = book.assign_speaker_ids()
    assert book.speaker_id_for("char_01") != book.speaker_id_for("char_02")  # 唯一

    # Storyboard Builder（mock LLM 返回结构化分镜）
    sb_out = {
        "title": "邂逅", "characters": ["char_01", "char_02"],
        "scenes": [{"scene_id": "s1", "title": "相遇", "location": "街角",
                    "synopsis": "A 牵 B 的手", "characters": ["char_01", "char_02"],
                    "shots": [{"shot_id": "s1sh1", "summary": "全景",
                               "action": "A 握住 B 的手", "camera": "",
                               "characters": ["char_01", "char_02"]}]}]}
    gw_sb = FakeGateway(json.dumps(sb_out))
    monkeypatch.setattr(sb_mod, "Gateway", lambda: gw_sb)
    sbn = sb_mod.APS_StoryboardBuilder()
    sb_json, _, _ = sbn.build(AI_PROFILE=payload, story_text="A 与 B 在街角相遇，A 握住 B 的手。",
                              split_mode="scene", target_duration=10.0,
                              max_scenes=4, style="", character_bible=None,
                              character_book=book.to_json(),
                              reference_manifest=None)
    sb = Storyboard.from_json(sb_json)
    assert "char_01" in sb.characters and "char_02" in sb.characters

    # Book + Storyboard → Prompt Composer ANIMA Natural（人物信息正确传递）
    gw = FakeGateway(json.dumps({
        "normal_form_version": "2.0",
        "characters": [
            {"character_id": "char_01", "name": "A",
             "required_traits": ["black short hair"],
             "variable_traits": ["white military uniform"],
             "action": "holds B's hand", "position": "left"},
            {"character_id": "char_02", "name": "B",
             "required_traits": ["long blonde hair"],
             "variable_traits": ["black dress"], "action": "", "position": "right"},
        ],
        "scene_description": "At the street corner.",
        "environment": [], "style": [], "composition": "", "lighting": "",
        "negative_constraints": []}))
    monkeypatch.setattr(pc_mod, "Gateway", lambda: gw)
    comp = pc_mod.APS_PromptComposer()
    positive, _, _, _, _ = comp.compose(
        AI_PROFILE=payload, text=json.dumps(sb.to_json()), target="anima_base",
        operation="generate", prompt_mode="natural_language", negative="",
        safety_tag="none", story_item=None, character_bible=None,
        character_book=book.to_json())
    # 属性绑定正确：白色军装属于 A、黑色礼服属于 B，不串位
    assert "white military uniform" in positive
    assert "black dress" in positive
    a_part, _, b_part = positive.partition("long blonde hair")
    assert "black dress" not in a_part


# ================================================================ Flow 4/5/6：Generic / SDXL / FLUX

@pytest.mark.parametrize("target,prompt_mode", [
    (t, m) for t in ["generic_image", "sdxl", "flux_kontext"]
    for m in ["tags", "natural_language"]])
def test_flow4_5_6_composer_generic_families(store, target, prompt_mode):
    """CharacterBook → Storyboard → Composer generic_image/sdxl/flux 必须成功（0.2.1 P0-1 回归）。

    0.2.1a：text 只写剧情（不预写任何人物特征）——两个角色的外貌特征
    必须来自 CharacterBook 本身（全部人物进最终 prompt，不再只取第一个档案）。
    0.2.1b：natural_language 模式也必须消费 CharacterBook（不再丢弃为 tag soup）。
    """
    payload = make_profile(store)
    book = two_char_book()
    comp = pc_mod.APS_PromptComposer()
    positive, negative, plan_json_out, profile_json, validation = comp.compose(
        AI_PROFILE=payload, text="A holds B's hand",
        target=target, operation="generate", prompt_mode=prompt_mode, negative="",
        safety_tag="none", character_bible=None, character_book=book.to_json())
    # 不再抛 TypeError/NameError；产出合法提示词
    assert positive and positive.strip()
    # 两个角色的特征都来自 CharacterBook（text 不含任何外貌特征）
    assert "black short hair" in positive
    assert "white military uniform" in positive
    assert "long blonde hair" in positive
    assert "black dress" in positive
    if prompt_mode == "natural_language":
        # 自然语句而非 tag soup：正文保留 + 人物特征以自然句形式在前
        assert "A holds B's hand" in positive
        assert "with" in positive
        assert not positive.startswith(",")
    plan = PromptPlan.from_json(plan_json_out)
    assert plan.target_family in ("generic_image", "sdxl", "flux")
    # 0.2.1b：PROMPT_PLAN metadata 记录全部人物（不只是第一个档案）
    assert len(plan.character_bindings) == 2
    names = {b["character"] for b in plan.character_bindings}
    assert names == {"A", "B"}


# ================================================================ Flow 7：H3 全链路

def test_flow7_book_storyboard_manifest_h3(monkeypatch, store):
    payload = make_profile(store)
    book = two_char_book()
    sb = Storyboard(title="t", characters=["char_01", "char_02"],
                    scenes=[Scene(title="s1", characters=["char_01", "char_02"],
                                  shots=[Shot(summary="A 与 B 相遇", characters=["char_01", "char_02"]),
                                         Shot(summary="A 牵起 B 的手", characters=["char_01", "char_02"])])])
    manifest = {"assets": [{"asset_id": "img_1", "asset_type": "image",
                            "path_or_ref": "ref1", "note": "首帧"}],
                "subjects": [{"subject_id": "subj_1", "kind": "character",
                              "definition": "the girl with long blonde hair",
                              "source_assets": ["img_1"]}],
                "character_sources": {}, "notes": ""}

    h3_plan = {
        "style_opening": "", "summary": "",
        "speakers": [{"speaker_id": "S1", "name": "A", "description": "black short hair"},
                     {"speaker_id": "S2", "name": "B", "description": "long blonde hair"}],
        "subjects": [{"label": "Subject 1", "kind": "character",
                      "definition": "B from <Picture 1>"}],
        "assets": [{"label": "Picture 1", "kind": "picture", "source": "1",
                    "alignment_time": 0.0},
                   {"label": "Audio 1", "kind": "audio", "source": "", "note": "city ambience"}],
        "retention": [{"label": "Subject 1", "marker": "fully_preserved",
                       "notes": "kept", "shot_refs": ["Shot 1"]}],
        "soundscape": "City sounds softly.",
        "non_diegetic_music": "N/A",
        "shots": [{"index": 1, "start_time": None,
                   "description": ["A and B meet."], "camera": "",
                   "characters": ["S1", "S2"], "dialogues": []},
                  {"index": 2, "start_time": 5.0,
                   "description": ["A holds B's hand."], "camera": "",
                   "characters": ["S1", "S2"], "dialogues": []}],
    }
    gw = FakeGateway(json.dumps(h3_plan))
    monkeypatch.setattr(h3_mod, "Gateway", lambda: gw)
    node = h3_mod.APS_MiniMaxH3Director()
    prompt, plan_out, _, validation, warnings = node.direct(
        AI_PROFILE=payload, text="A 与 B 相遇", mode="T2VA",
        operation="convert_storyboard", duration=10.0,
        storyboard=sb.to_json(), character_book=book.to_json(),
        reference_manifest=json.dumps(manifest))
    plan = H3PromptPlan.from_json(plan_out)
    # 媒体独立编号：Picture 1 / Audio 1（同类型独立 1 起始）
    labels = [a.label for a in plan.assets]
    assert "Picture 1" in labels and "Audio 1" in labels
    # 时间戳：Shot 1 无时间戳、Shot 2 有且递增
    assert plan.shots[0].start_time is None
    assert plan.shots[1].start_time is not None
    assert plan.shots[1].start_time > 0
    # Speaker IDs 稳定
    assert {s.speaker_id for s in plan.speakers} == {"S1", "S2"}
    assert "[Shot 2] At 00:05.000," in prompt
    assert "通过" in validation


# ================================================================ Flow 8：离线 Audit（无 API Key）

def test_flow8_offline_audits_without_api_key(store):
    store.create_profile({"profile_id": "nokey", "name": "NoKey"})
    payload = store.get_profile("nokey").node_payload()   # 无 API Key

    # ANIMA audit 完全离线
    comp = pc_mod.APS_PromptComposer()
    positive, negative, plan_json_out, _, validation = comp.compose(
        AI_PROFILE=payload, text="Long_Hair, 1girl, 1girl", target="anima_base",
        operation="audit", prompt_mode="tags", negative="",
        safety_tag="none", character_bible=None)
    assert "anima_uppercase" in validation
    assert "anima_duplicate" in validation

    # H3 audit 完全离线
    node = h3_mod.APS_MiniMaxH3Director()
    good = ("[Shot 1] A girl enters the cafe.\n"
            "overall_soundscape: The cafe hums softly.\n"
            "non_diegetic_music: N/A")
    prompt, plan_json_out, _, validation, _ = node.direct(
        AI_PROFILE=payload, text=good, mode="T2VA",
        operation="audit", duration=10.0)
    assert prompt == good
    assert "通过" in validation

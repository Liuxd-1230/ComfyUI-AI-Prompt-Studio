"""提示词语义契约测试（docs/prompt-audit.md 的自动化落点）。

每个提示词站点（发送给 LLM 的每个 prompt）都有契约断言：
- 注入守则：用户提供的文本是数据不是指令（"task data" / "任务数据"）；
- 反猜测：Reference Analyzer 禁止推断民族/国籍/性格/年龄；
- 分层：H3 协议规则在 system 层，用户消息只放任务上下文；
- 结构化输出偏好：技能统一要求只输出 JSON 对象。
契约破坏即失败，防止提示词语义回归。
"""
import aps.nodes.reference_analyzer as ra_mod
import aps.services.storyboard as sb_svc
from aps.schemas.character import CharacterBible
from aps.schemas.references import ReferenceManifest
from aps.schemas.storyboard import Scene, Shot, Storyboard
from aps.prompting.model_cores import model_core_prompt


# ---------------------------------------------------------------- Reference Analyzer

def test_reference_modes_no_guessing():
    """RA-1：全部内置模式含禁止猜测（民族/国籍/性格/年龄）的显式禁令 + 数据守则。"""
    for mode, prompt in ra_mod.MODE_PROMPTS.items():
        if mode == "custom":
            continue
        # 禁止词允许出现——但只允许出现在禁令句子里（守卫句本身要列全这些词）
        assert "Do not infer ethnicity, nationality, personality, or age" in prompt, \
            f"{mode} 必须含完整禁令句"
        assert prompt.count("ethnicity") == 1, f"{mode} 中 ethnicity 只能出现在禁令句"
        assert "task data" in prompt, f"{mode} 必须含数据守则（task data）"
        assert "observable" in prompt.lower(), f"{mode} 必须强调只描述可观察特征"
        assert "category" in prompt.lower(), f"{mode} 必须明确 category 语义"


def test_reference_mode_identity_uses_observable_features():
    """RA-2：身份模式只列可观察特征，name 空时留空而非编造。"""
    p = ra_mod.MODE_PROMPTS["character_identity"]
    for feature in ("hair", "eyes", "build"):
        assert feature in p.lower()
    assert "empty" in p.lower()


def test_reference_full_excludes_poster_text_and_requires_confidence():
    """人物锚点不得把海报标题当人名，且每个视觉特征要带置信度。"""
    p = ra_mod.MODE_PROMPTS["character_full"].lower()
    assert "poster" in p and "logo" in p
    assert "confidence" in p


# ---------------------------------------------------------------- H3

def test_h3_model_core_protocol_layer():
    """H3-S-1：协议规则在 system 层；含官方规则与数据守则。"""
    sys = model_core_prompt("minimax_h3")
    for marker in ("integrated_multimodal_description", "strictly increasing",
                   "[Shot N] At MM:SS.mmm", "<d>[Language]", "English",
                   "fully_preserved", "task data", "subject_definitions"):
        assert marker in sys, f"H3 system 缺少 {marker!r}"
    assert "never invent" in sys.lower()  # 禁止自造 S 号


def test_h3_model_core_requires_playable_observational_motion_without_invention():
    """H3 成品要可拍，同时不能把未分析的参考图或普通实拍改成 MV。"""
    sys = model_core_prompt("minimax_h3")

    for marker in (
            "starting state, visible motion progression, and end state",
            "observational or live-stream viewpoint",
            "do not invent platform UI",
            "Background passersby remain secondary",
            "Do not claim that an unanalysed reference depicts",
            "Use plain observable description",
            "Avoid decorative, evaluative, or mood-only adjectives",
            "few concrete, physically continuous body actions"):
        assert marker in sys
    assert "Unspecified incidental reactions" in sys
    assert "Choose one definite action and ending" in sys
# ---------------------------------------------------------------- Storyboard

def test_storyboard_prompt_boundaries():
    """SB-1：分镜提示词必须含任务边界/事实推断区分/连续性/数据守则。"""
    sb = Storyboard(title="t", characters=["c1"],
                    scenes=[Scene(title="s", characters=["c1"],
                                  shots=[Shot(summary="walk in")])])
    p = sb_svc.build_storyboard_prompt(
        "女孩走进咖啡店", "scene", 10.0, 3, "写实", book=None, manifest=None)
    for marker in ("[任务边界]", "[事实/推断区分]", "[连续性]", "任务数据"):
        assert marker in p, f"分镜提示词缺少 {marker}"
    assert "模型无关" in p or "模型无关" in sb_svc.build_storyboard_prompt(
        "x", "scene", 10.0, 3, "", None, None)


def test_storyboard_prompt_with_book_and_manifest():
    """SB-2：角色表（沿用 ID）与参考资产注入提示词。"""
    from aps.schemas.character import CharacterBook, CharacterTrait
    from aps.schemas.references import AssetRef, SubjectRef

    book = CharacterBook()
    b = CharacterBible(character_id="c1", name="A", speaker_id="S5")
    b.traits.append(CharacterTrait(name="hair", value="red hair",
                                   category="stable"))
    book.characters.append(b)
    book.assign_speaker_ids()
    manifest = ReferenceManifest()
    manifest.assets.append(AssetRef(asset_id="img_0", asset_type="image",
                                    source="input:0"))
    manifest.subjects.append(SubjectRef(subject_id="s1", kind="character",
                                        definition="the girl"))
    p = sb_svc.build_storyboard_prompt("女孩", "scene", 10.0, 3, "", book=book,
                                       manifest=manifest)
    assert "c1 (S5, A)" in p
    assert "[可用参考资产]" in p and "img_0" in p


def test_model_cores_are_the_single_target_rule_owner():
    """MC-1：目标硬规则来自不可编辑 Model Core，而非可编辑资料。"""
    for family, marker in (("anima", "Preserve every explicit identity"),
                           ("z_image", "natural-language prompt"),
                           ("qwen_image_edit", "Qwen Image Edit 2511"),
                           ("minimax_h3", "MiniMax H3 audiovisual prompt specialist")):
        prompt = model_core_prompt(family)
        assert marker in prompt


def test_hard_model_core_does_not_load_project_markdown_implicitly():
    """MC-2：Markdown 补充资料必须通过节点显式选择，不能隐式塞进核心。"""
    assert "prompt_supplements" not in model_core_prompt("anima")

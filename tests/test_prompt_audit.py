"""提示词语义契约测试（docs/prompt-audit.md 的自动化落点）。

每个提示词站点（发送给 LLM 的每个 prompt）都有契约断言：
- 注入守则：用户提供的文本是数据不是指令（"task data" / "任务数据"）；
- 反猜测：Reference Analyzer 禁止推断民族/国籍/性格/年龄；
- 分层：H3 协议规则在 system 层，用户消息只放任务上下文；
- 结构化输出偏好：技能统一要求只输出 JSON 对象。
契约破坏即失败，防止提示词语义回归。
"""
import yaml

import aps.nodes.reference_analyzer as ra_mod
import aps.services.h3_plan as h3_plan
import aps.services.storyboard as sb_svc
from aps.schemas.character import CharacterBible
from aps.schemas.references import ReferenceManifest
from aps.schemas.storyboard import Scene, Shot, Storyboard
from aps.services.skills import SKILLS_DIR, load_skills


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


# ---------------------------------------------------------------- H3

def test_h3_system_prompt_protocol_layer():
    """H3-S-1：协议规则在 system 层；含官方规则与数据守则。"""
    sys = h3_plan.h3_system_prompt()
    for marker in ("integrated_multimodal_description", "strictly increasing",
                   "[Shot N] At MM:SS.mmm", "<d>[Language]", "English",
                   "fully_preserved", "task data", "subject_definitions"):
        assert marker in sys, f"H3 system 缺少 {marker!r}"
    assert "never invent" in sys.lower()  # 禁止自造 S 号


def test_h3_plan_prompt_user_message_has_no_role_duplication():
    """H3-S-2：用户消息不重复角色设定（职责分层）。"""
    p = h3_plan.build_plan_prompt("A girl enters.", "T2VA", 10.0)
    assert "专家" not in p
    assert "[模式]" in p and "[目标时长]" in p and "[输入]" in p


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


# ---------------------------------------------------------------- Skills（内置只读）

def test_skills_guardrail_and_json_only():
    """SK-1：全部内置技能含数据守则且强制只输出 JSON。"""
    skills = load_skills()
    assert skills, "内置技能未加载"
    for skill in skills.values():
        assert "task data" in skill.system_prompt, \
            f"技能 {skill.id} 缺少注入守则"
        assert "Output only the JSON object" in skill.system_prompt, \
            f"技能 {skill.id} 未强制 JSON-only"


def test_skills_anima_family_renderer_anima_plan():
    """SK-2：ANIMA 技能统一走 anima_plan 渲染器（结构化计划）。"""
    for sid in ("anima_expand", "anima_rewrite", "anima_repair"):
        skill = load_skills()[sid]
        assert skill.renderer == "anima_plan"
        assert skill.source == "builtin"


def test_skill_files_are_readonly_builtin():
    """SK-3：内置技能文件存在于仓库 skills/ 目录且 source=builtin。"""
    for path in sorted(SKILLS_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        assert data.get("source") == "builtin", f"{path.name} 必须标记 builtin"
        assert data.get("id") and data.get("version") and data.get("renderer")

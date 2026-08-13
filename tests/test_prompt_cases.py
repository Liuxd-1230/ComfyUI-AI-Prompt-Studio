"""Prompt 回归用例：tests/prompt_cases/*.json 的确定性执行器。

每个用例文件声明 pipeline + input + expect（观测字典）。执行器跑确定性管线
（不调 LLM），收集观测值并与 expect 逐项比对。用于防止提示词/渲染语义回归
（docs/prompt-audit.md 的 regression cases：Case1 单锚点、Case2 多人物不串位、
Case3 多图共识、Case4 H3 Ref2VA 英文要求）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

CASES_DIR = Path(__file__).parent / "prompt_cases"

from aps.renderers.anima import AnimaCharacter, AnimaPromptPlan, render_anima_plan  # noqa: E402
from aps.renderers.minimax_h3 import render_h3  # noqa: E402
from aps.schemas.character import CharacterCandidate, CharacterTrait  # noqa: E402
from aps.schemas.references import AssetRef  # noqa: E402
from aps.services import reference as reference_svc  # noqa: E402
from aps.services.h3_plan import parse_plan_json  # noqa: E402
from aps.validators.minimax_h3 import ref2va_english_issue  # noqa: E402


def _case_files():
    return sorted(CASES_DIR.glob("case*.json"))


# ---------------------------------------------------------------- 管线

def _pipeline_reference_anchor(inp):
    traits = reference_svc.parse_anchor_fragments(inp["text_anchor"])
    return {
        "trait_count": len(traits),
        "all_stable": bool(traits) and all(t.category == "stable" for t in traits),
        "all_sources_text_anchor": bool(traits) and all(
            t.sources == ["text_anchor"] for t in traits),
    }


def _pipeline_anima_multi_char(inp):
    plan = AnimaPromptPlan(
        characters=[AnimaCharacter(
            character_id=c["character_id"], name=c["name"],
            required_traits=[t["value"] for t in c["traits"]
                             if t["category"] == "stable"],
            variable_traits=[t["value"] for t in c["traits"]
                             if t["category"] != "stable"])
            for c in inp["characters"]],
        scene_description="")
    result = render_anima_plan(plan, variant="base",
                               prompt_mode=inp["prompt_mode"])
    positive = result.positive
    # 按人物名切块：每段只属于该人物，检查属性不串位
    obs = {}
    for c in inp["characters"]:
        name = c["name"]
        for t in c["traits"]:
            key = t["value"].split()[0].lower()
            # 该特征应出现在自己的人物块
            obs[f"{key}_in_{name}"] = key in positive.lower()
            # 该特征不应出现在其他人物块
            for other in inp["characters"]:
                if other["name"] != name:
                    obs[f"{key}_in_{other['name']}"] = False
    return obs


def _pipeline_multi_image_consensus(inp):
    candidates = [CharacterCandidate(
        name=c["name"],
        traits=[CharacterTrait(name=t["name"], value=t["value"],
                               category=t["category"],
                               confidence=t["confidence"], sources=t["sources"])
                for t in c["traits"]])
        for c in inp["candidates"]]
    merged = reference_svc.consensus_of(candidates)
    hair = next((t for t in merged.traits if t.name == "hair"), None)
    assets = [AssetRef(asset_id=f"img_{i}", asset_type="image",
                       source=f"input:{i}") for i in range(2)]
    manifest = reference_svc.build_manifest(assets, [merged])
    return {
        "hair_category": hair.category if hair else "none",
        "conflict_count": len(getattr(merged, "conflicts", [])),
        "subject_count": len(manifest.subjects),
        "asset_count": len(manifest.assets),
    }


def _pipeline_h3_ref2va_english(inp):
    cn = parse_plan_json(json.dumps(inp["chinese_plan"]), "Ref2VA", 10.0)
    en = parse_plan_json(json.dumps(inp["english_plan"]), "Ref2VA", 10.0)
    cn_rendered = render_h3(cn)
    en_rendered = render_h3(en)
    # 六段固定顺序
    heads = ["subject_definitions:", "summary:", "retention_analysis:",
             "detailed_description:", "overall_soundscape:",
             "non_diegetic_music:"]
    idx = [cn_rendered.find(h) for h in heads]
    order_ok = all(idx[i] != -1 and idx[i] < idx[i + 1] for i in range(len(idx) - 1))
    return {
        "chinese_flagged": ref2va_english_issue(cn_rendered) is not None,
        "english_flagged": ref2va_english_issue(en_rendered) is not None,
        "section_order_ok": order_ok,
    }


_PIPELINES = {
    "reference_anchor": _pipeline_reference_anchor,
    "anima_multi_char": _pipeline_anima_multi_char,
    "multi_image_consensus": _pipeline_multi_image_consensus,
    "h3_ref2va_english": _pipeline_h3_ref2va_english,
}


# ---------------------------------------------------------------- 用例

@pytest.mark.parametrize("case_path", [str(p) for p in _case_files()],
                         ids=[p.stem for p in _case_files()])
def test_prompt_case(case_path):
    case = json.loads(Path(case_path).read_text(encoding="utf-8"))
    pipeline = _PIPELINES.get(case["pipeline"])
    assert pipeline is not None, f"未知 pipeline: {case['pipeline']}"
    obs = pipeline(case["input"])
    for key, expected in case["expect"].items():
        assert obs.get(key) == expected, (
            f"[{case['name']}] 观测 {key}={obs.get(key)!r} != 期望 {expected!r}")


def test_prompt_case_files_valid():
    """每个用例文件都有 pipeline 且 expect 非空。"""
    for p in _case_files():
        case = json.loads(p.read_text(encoding="utf-8"))
        assert case["pipeline"] in _PIPELINES
        assert case["expect"]
        assert case.get("name")

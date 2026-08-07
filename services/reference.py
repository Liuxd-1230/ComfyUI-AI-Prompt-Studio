"""参考分析核心逻辑（纯函数，可离线测试）：
文字锚点片段解析、模型 JSON 容错解析、多图共识/冲突、Bible 合并策略、Manifest 构建。

策略语义（docs/decisions.md 补充）：
- manual_priority：人工锁定字段（locked）永不被覆盖；其余以现有档案为准；
- text_priority：source 含 text_anchor 的特征优先；
- image_priority：source 以 image 开头的特征优先（锁定仍优先）；
- consensus：同特征取置信度/支持度最高者；冲突记录为 uncertain + conflict；
- fill_missing_only：只补缺失特征名，绝不覆盖。
"""
from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

from ..schemas.character import (
    CharacterBible,
    CharacterCandidate,
    CharacterConflict,
    CharacterTrait,
)
from ..schemas.references import AssetRef, ReferenceManifest, SubjectRef

_TRAIT_CATEGORIES = {"stable", "variable", "current", "uncertain"}


# ------------------------------------------------------------------ 解析

def parse_anchor_fragments(text: str) -> List[CharacterTrait]:
    """把文字锚点按 、，,;/\n 切分为 stable 特征（确定性，离线可用）。

    片段整体作为 value（保留原文），供 character_prompt 直接渲染。
    """
    if not text or not text.strip():
        return []
    parts = [p.strip() for p in re.split(r"[、，,;；/\n]+", text) if p.strip()]
    return [CharacterTrait(name=f"anchor_{i}", value=p, category="stable",
                           confidence=0.9, sources=["text_anchor"])
            for i, p in enumerate(parts)]


def extract_json_object(raw: str) -> Optional[dict]:
    """从模型输出中容错提取第一个 JSON 对象。"""
    if not raw:
        return None
    raw = raw.strip()
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except ValueError:
        pass
    # 在 ```json ... ``` 或花括号块中找
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except ValueError:
        return None


def parse_candidate_json(raw: str, mode: str = "character_full",
                         sources: Optional[List[str]] = None) -> CharacterCandidate:
    """把模型输出的 JSON 解析为 CharacterCandidate（容错，失败给空候选）。"""
    candidate = CharacterCandidate(analysis_mode=mode,
                                   sources=list(sources or []), raw=raw or "")
    data = extract_json_object(raw)
    if data is None:
        candidate.confidence = 0.0
        return candidate
    if isinstance(data.get("name"), str) and data["name"].strip():
        candidate.name = data["name"].strip()
    for t in data.get("traits") or []:
        if not isinstance(t, dict):
            continue
        name = str(t.get("name", "")).strip()
        value = str(t.get("value", "")).strip()
        if not name or not value:
            continue
        category = str(t.get("category", "stable"))
        if category not in _TRAIT_CATEGORIES:
            category = "stable"
        try:
            confidence = float(t.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        candidate.traits.append(CharacterTrait(
            name=name, value=value, category=category,
            confidence=min(max(confidence, 0.0), 1.0),
            sources=list(sources or [])))
    return candidate


def consensus_of(candidates: List[CharacterCandidate]) -> CharacterCandidate:
    """多图共识：同一特征名取支持数最多/置信度最高的值；平分秋色 → uncertain + conflict。

    返回新候选（不修改入参）。仅合并 stable/variable/current 类特征；
    uncertain 特征原样保留（本身即不确定）。
    """
    merged = CharacterCandidate(analysis_mode="consensus")
    by_name: Dict[str, List[CharacterTrait]] = {}
    for c in candidates:
        merged.sources.extend(s for s in c.sources if s not in merged.sources)
        for t in c.traits:
            by_name.setdefault(t.name, []).append(t)

    conflicts: List[CharacterConflict] = []
    for name, traits in by_name.items():
        values = {t.value for t in traits}
        if len(values) > 1:
            best = max(traits, key=lambda t: (t.confidence, len(t.sources)))
            conflicts.append(CharacterConflict(
                trait_name=name, values=sorted(values),
                reason="多图推断不一致，取置信度最高者",
                resolution_hint="可手动锁定该特征或补充更清晰的参考图"))
            merged.traits.append(CharacterTrait(
                name=name, value=best.value, category="uncertain",
                confidence=best.confidence, sources=list(best.sources)))
        else:
            t = traits[0]
            merged.traits.append(CharacterTrait(
                name=name, value=t.value, category=t.category,
                confidence=t.confidence, sources=list(t.sources)))
    return merged


# ------------------------------------------------------------------ Bible 合并

def _sources_match(trait: CharacterTrait, prefix: str) -> bool:
    return any(s.startswith(prefix) for s in trait.sources)


def merge_candidate_into_bible(
    bible: CharacterBible,
    candidate: CharacterCandidate,
    strategy: str,
) -> CharacterBible:
    """把候选特征并入 Bible（按策略；锁定字段永不覆盖；冲突记录）。"""
    existing = bible.trait_map()
    for t in candidate.traits:
        cur = existing.get(t.name)
        if cur is None:
            bible.traits.append(CharacterTrait(
                name=t.name, value=t.value, category=t.category,
                confidence=t.confidence, sources=list(t.sources)))
            continue

        # 锁定字段永不被覆盖
        if cur.locked or cur.name in bible.locked_fields:
            if cur.value != t.value:
                bible.conflicts.append(CharacterConflict(
                    trait_name=t.name, values=[cur.value, t.value],
                    reason="与已锁定字段冲突（锁定优先）"))
            continue

        if cur.value == t.value:
            # 同值：合并来源与置信度上限
            cur.sources.extend(s for s in t.sources if s not in cur.sources)
            cur.confidence = max(cur.confidence, t.confidence)
            continue

        # 值不同 → 按策略裁决
        if strategy == "fill_missing_only":
            bible.conflicts.append(CharacterConflict(
                trait_name=t.name, values=[cur.value, t.value],
                reason="fill_missing_only 不覆盖已有特征"))
            continue

        if strategy == "text_priority":
            if _sources_match(t, "text_anchor") and not _sources_match(cur, "text_anchor"):
                _replace_trait(cur, t)
            else:
                bible.conflicts.append(CharacterConflict(
                    trait_name=t.name, values=[cur.value, t.value],
                    reason="text_priority：新特征无文字锚点来源"))
            continue

        if strategy == "image_priority":
            if _sources_match(t, "image") and not _sources_match(cur, "image"):
                _replace_trait(cur, t)
            else:
                bible.conflicts.append(CharacterConflict(
                    trait_name=t.name, values=[cur.value, t.value],
                    reason="image_priority：新特征无图片来源"))
            continue

        if strategy == "consensus":
            if t.confidence > cur.confidence + 1e-9:
                _replace_trait(cur, t)
            else:
                cur.category = "uncertain"
                bible.conflicts.append(CharacterConflict(
                    trait_name=t.name, values=[cur.value, t.value],
                    reason="consensus：置信度不足或持平，标记不确定"))
            continue

        # manual_priority：以现有档案为准
        bible.conflicts.append(CharacterConflict(
            trait_name=t.name, values=[cur.value, t.value],
            reason="manual_priority：保留现有档案"))
        continue

    if candidate.name and not bible.name:
        bible.name = candidate.name
    for s in candidate.sources:
        if s not in bible.sources:
            bible.sources.append(s)
    if candidate.confidence < 0.4:
        bible.uncertainty_notes.append(f"候选整体置信度低（{candidate.confidence:.2f}），特征需人工复核")
    bible.touch()
    return bible


def _replace_trait(cur: CharacterTrait, t: CharacterTrait) -> None:
    cur.value = t.value
    cur.category = t.category
    cur.confidence = t.confidence
    cur.sources = list(t.sources)


# ------------------------------------------------------------------ Manifest

def build_manifest(asset_refs: List[AssetRef], candidates: List[CharacterCandidate],
                   notes: str = "") -> ReferenceManifest:
    """从资产与候选构建 Manifest：资产注册 + Subject 映射 + character_sources。"""
    manifest = ReferenceManifest()
    manifest.notes = notes
    for a in asset_refs:
        manifest.add_asset(a)

    subject_index: Dict[str, SubjectRef] = {}
    for c in candidates:
        cid = f"subject_{len(subject_index) + 1}"
        subject = SubjectRef(subject_id=cid, kind="character",
                             definition=c.name or cid,
                             source_assets=[a.asset_id for a in asset_refs],
                             confidence=c.confidence)
        manifest.subjects.append(subject)
        subject_index.setdefault(c.name or cid, subject)
        # 每个来源资产归属该人物
        for a in asset_refs:
            if a.asset_id not in manifest.character_sources.setdefault(cid, []):
                manifest.character_sources[cid].append(a.asset_id)
    return manifest

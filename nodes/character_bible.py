"""节点 4：Character Bible —— 融合文字锚点/视觉候选/已有档案，管理人物稳定身份。

合并策略（services/reference.merge_candidate_into_bible）：
manual_priority / text_priority / image_priority / consensus / fill_missing_only；
人工锁定字段永不被覆盖；冲突记录进 conflict_report；人物 ID + H3 Speaker ID 自动分配。
"""
from __future__ import annotations

import json

from ..schemas import types
from ..schemas.character import MERGE_STRATEGIES, CharacterBible, CharacterCandidate
from ..services import reference as reference_svc


class APS_CharacterBible:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "merge_strategy": (MERGE_STRATEGIES, {"default": "consensus",
                                                  "tooltip": "manual_priority=人工锁定优先；text_priority=文字优先；image_priority=图片优先；consensus=共识合并；fill_missing_only=只补缺失"}),
        }, "optional": {
            "character_candidate": (types.CHARACTER_CANDIDATE,),
            "existing_bible": (types.CHARACTER_BIBLE,),
            "text_anchor": ("STRING", {"default": "", "multiline": True,
                                       "tooltip": "直接输入的文字锚点片段（追加为 stable 特征，source=text_anchor）"}),
            "lock_fields": ("STRING", {"default": "", "multiline": False,
                                       "tooltip": "要锁定的特征名（逗号分隔），锁定后任何策略都不可覆盖"}),
            "character_name": ("STRING", {"default": "", "multiline": False,
                                          "tooltip": "人物名（未指定时取候选名称）"}),
        }}

    RETURN_TYPES = (types.CHARACTER_BIBLE, "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("CHARACTER_BIBLE", "character_prompt", "json", "conflict_report", "uncertainty")
    FUNCTION = "merge"
    CATEGORY = "AI Prompt Studio"
    DESCRIPTION = "把文字锚点、视觉候选与已有档案合并为人物稳定身份（锁定字段/冲突报告/来源追踪）。"

    def merge(self, merge_strategy, character_candidate=None, existing_bible=None,
              text_anchor="", lock_fields="", character_name=""):
        bible = CharacterBible.from_json(existing_bible) if existing_bible else CharacterBible()

        # 锁定字段
        if lock_fields and lock_fields.strip():
            for name in [n.strip() for n in lock_fields.split(",") if n.strip()]:
                if name not in bible.locked_fields:
                    bible.locked_fields.append(name)
            for t in bible.traits:
                if t.name in bible.locked_fields:
                    t.locked = True

        # 文字锚点片段（确定性追加，source=text_anchor）
        if text_anchor and text_anchor.strip():
            for t in reference_svc.parse_anchor_fragments(text_anchor.strip()):
                if t.name in bible.trait_map():
                    continue
                bible.traits.append(t)
                if t.name not in bible.sources:
                    bible.sources.append("text_anchor")

        # 候选合并
        if character_candidate:
            candidate = CharacterCandidate.from_json(character_candidate)
            reference_svc.merge_candidate_into_bible(bible, candidate, merge_strategy)

        if character_name and character_name.strip() and not bible.name:
            bible.name = character_name.strip()
        if not bible.name and character_candidate:
            cand = CharacterCandidate.from_json(character_candidate)
            if cand.name:
                bible.name = cand.name

        bible.touch()
        return (bible.to_json(), bible.character_prompt(),
                bible.to_json_string(), bible.conflict_report_text(),
                bible.uncertainty_text())

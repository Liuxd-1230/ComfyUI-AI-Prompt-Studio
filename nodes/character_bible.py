"""节点 4：Character Bible —— 融合文字锚点/视觉候选/已有档案，管理人物稳定身份。

合并策略（services/reference.merge_candidate_into_bible）：
manual_priority / text_priority / image_priority / consensus / fill_missing_only；
人工锁定字段永不被覆盖；冲突记录进 conflict_report；人物 ID + H3 Speaker ID 自动分配。

多人物（docs/decisions.md D17）：CharacterBook 容器按 character_id 去重，
统一分配唯一 Speaker ID（char_01→S1...，删除不改动他人 ID，冲突修复并记 warning）。
节点输出 CHARACTER_BIBLE（当前人物）与 CHARACTER_BOOK（容器）双路。
"""
from __future__ import annotations

import json
import uuid

from ..schemas import types
from ..schemas.character import (
    MERGE_STRATEGIES,
    CharacterBible,
    CharacterBook,
    CharacterCandidate,
)
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
            "existing_book": (types.CHARACTER_BOOK,),
            "text_anchor": ("STRING", {"default": "", "multiline": True,
                                       "tooltip": "直接输入的文字锚点片段（追加为 stable 特征，source=text_anchor）"}),
            "lock_fields": ("STRING", {"default": "", "multiline": False,
                                       "tooltip": "要锁定的特征名（逗号分隔），锁定后任何策略都不可覆盖"}),
            "character_name": ("STRING", {"default": "", "multiline": False,
                                          "tooltip": "人物名（未指定时取候选名称）"}),
        }}

    RETURN_TYPES = (types.CHARACTER_BIBLE, "STRING", "STRING", "STRING", "STRING",
                    types.CHARACTER_BOOK, "STRING")
    RETURN_NAMES = ("CHARACTER_BIBLE", "character_prompt", "json", "conflict_report",
                    "uncertainty", "CHARACTER_BOOK", "warnings")
    FUNCTION = "merge"
    CATEGORY = "AI Prompt Studio"
    DESCRIPTION = "把文字锚点、视觉候选与已有档案合并为人物稳定身份；维护多人物 CharacterBook 与唯一 Speaker ID。"

    def merge(self, merge_strategy, character_candidate=None, existing_bible=None,
              existing_book=None, text_anchor="", lock_fields="", character_name=""):
        # 多人物容器：没有 Book 就新建；有 Book 则按 character_id 添加/更新
        book = CharacterBook.from_json(existing_book) if existing_book else CharacterBook()
        candidate = CharacterCandidate.from_json(character_candidate) if character_candidate else None

        # 名称提示：优先 character_name，其次候选名（更新路径按同名匹配 Book 中已有档案）
        name_hint = (character_name or "").strip()
        if not name_hint and candidate is not None and candidate.name:
            name_hint = candidate.name.strip()

        bible = None
        # 1) Book 中已有同名人物 → 直接更新（保留 character_id / Speaker ID / 锁定）
        if name_hint:
            bible = book.find_by_name(name_hint)
        # 2) 无名称提示时：Book 中唯一人物（候选合并场景）
        if bible is None and candidate is not None and len(book.characters) == 1:
            bible = book.characters[0]
        # 3) 兜底：existing_bible 或新建
        if bible is None:
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
                if "text_anchor" not in bible.sources:
                    bible.sources.append("text_anchor")

        # 候选合并
        if candidate is not None:
            reference_svc.merge_candidate_into_bible(bible, candidate, merge_strategy)

        # The explicit UI name is authoritative display identity. A model-inferred
        # candidate name (including a plausible but wrong label) must not override it.
        if character_name and character_name.strip():
            bible.name = character_name.strip()
        if not bible.name and candidate is not None and candidate.name:
            bible.name = candidate.name
        if not bible.character_id and bible.name:
            # 名称只用于展示；ID 使用不可碰撞、语言无关的稳定句柄。
            bible.character_id = "char_" + uuid.uuid4().hex[:12]

        bible.touch()

        # 写入容器：按 character_id 去重 upsert；统一分配唯一 Speaker ID
        book.upsert_character(bible)
        warnings = book.assign_speaker_ids()
        book.default_character_id = bible.character_id
        warnings_text = "\n".join(warnings) if warnings else ""

        return (bible.to_json(), bible.character_prompt(),
                bible.to_json_string(), bible.conflict_report_text(),
                bible.uncertainty_text(), book.to_json(), warnings_text)

"""节点 4：Character Bible —— 融合文字锚点/视觉结果/已有档案，管理人物稳定身份。

Phase 1：注册与数据结构就绪；Phase 3 实现合并策略与冲突处理。
"""

from ..schemas import types
from ..schemas.character import MERGE_STRATEGIES, CharacterBible


class APS_CharacterBible:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "text_anchor": ("STRING", {"default": "", "multiline": True,
                                       "tooltip": "文字锚点：明确的人物设定（优先级高于图片推断）"}),
            "merge_strategy": (MERGE_STRATEGIES, {"default": "consensus",
                                                  "tooltip": "manual_priority=人工锁定优先；text_priority=文字优先；image_priority=图片优先；consensus=共识合并；fill_missing_only=只补缺失"}),
        }, "optional": {
            "character_candidate": (types.CHARACTER_CANDIDATE,),
            "existing_bible": (types.CHARACTER_BIBLE,),
        }}

    RETURN_TYPES = (types.CHARACTER_BIBLE, "STRING", "STRING", "STRING")
    RETURN_NAMES = ("CHARACTER_BIBLE", "character_prompt", "json", "conflict_report")
    FUNCTION = "merge"
    CATEGORY = "AI Prompt Studio"
    DESCRIPTION = "把文字锚点、视觉候选与已有档案合并为人物稳定身份（锁定字段/冲突报告/来源追踪）。"

    def merge(self, text_anchor, merge_strategy,
              character_candidate=None, existing_bible=None):
        bible = CharacterBible.from_json(existing_bible) if existing_bible else CharacterBible()
        if text_anchor:
            bible.sources.append("text_anchor")
        # Phase 3 实现合并：融合 candidate traits、锁定字段、冲突检测。
        return (bible.to_json(), bible.character_prompt(), bible.to_json_string(), bible.conflict_report_text())

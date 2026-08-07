"""节点 3：Reference Analyzer —— 视觉/文字参考分析、人物候选、参考清单。

Phase 1：注册与数据结构就绪；Phase 3 接入 vision 服务后完整实现。
"""

from ..schemas import types
from ..schemas.references import ANALYSIS_MODES, ReferenceAnalysis, ReferenceManifest
from ..schemas.character import CharacterCandidate


class APS_ReferenceAnalyzer:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "AI_PROFILE": (types.AI_PROFILE,),
            "analysis_mode": (ANALYSIS_MODES, {"default": "character_full",
                                               "tooltip": "分析模式：人物身份/全身/服装/姿态表情/场景/构图/风格/物件/ANIMA/H3/自定义"}),
            "text_anchor": ("STRING", {"default": "", "multiline": True,
                                       "tooltip": "文字锚点：已知的人物设定（如：红发少女，蓝裙子）"}),
        }, "optional": {
            "images": ("IMAGE", {"tooltip": "参考图片（支持批次；批次会逐图分析后做共识）"}),
            "character_bible": (types.CHARACTER_BIBLE,),
            "custom_prompt": ("STRING", {"default": "", "multiline": True,
                                         "tooltip": "analysis_mode=custom 时的自定义分析指令"}),
        }}

    RETURN_TYPES = (types.REFERENCE_ANALYSIS, types.CHARACTER_CANDIDATE, types.REFERENCE_MANIFEST,
                    "STRING", "STRING", "STRING")
    RETURN_NAMES = ("REFERENCE_ANALYSIS", "CHARACTER_CANDIDATE", "REFERENCE_MANIFEST",
                    "caption", "confidence", "raw")
    FUNCTION = "analyze"
    CATEGORY = "AI Prompt Studio"
    DESCRIPTION = "使用视觉模型分析图片/批次/视频与文字锚点，反推结构化参考信息与人物候选（保留原始资产）。"

    def analyze(self, AI_PROFILE, analysis_mode, text_anchor,
                images=None, character_bible=None, custom_prompt=""):
        profile_id = (AI_PROFILE or {}).get("profile_id", "")
        analysis = ReferenceAnalysis(mode=analysis_mode, profile_id=profile_id)
        analysis.warnings.append("Reference Analyzer 功能将在 Phase 3 接入视觉服务")
        candidate = CharacterCandidate(analysis_mode=analysis_mode, sources=["text_anchor"] if text_anchor else [])
        manifest = ReferenceManifest()
        return (analysis.to_json(), candidate.to_json(), manifest.to_json(),
                analysis.caption, str(analysis.confidence), analysis.raw)

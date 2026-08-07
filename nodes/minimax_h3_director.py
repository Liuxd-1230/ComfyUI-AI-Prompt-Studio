"""节点 8：MiniMax H3 Prompt Director —— 生成/改写/转换/审计/修复 H3 提示词。

Phase 1：注册与数据结构就绪；Phase 5 实现五种模式 renderer + validator + repair。
"""

from ..schemas import types
from ..schemas.h3 import H3_MODES, H3_OPERATIONS, H3PromptPlan


class APS_MiniMaxH3Director:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "AI_PROFILE": (types.AI_PROFILE,),
            "text": ("STRING", {"default": "", "multiline": True,
                                "tooltip": "剧情/画面/声音描述（R2V 模式为需要重写的参考视频描述）"}),
            "mode": (H3_MODES, {"default": "T2VA",
                                "tooltip": "T2VA=纯文本；I2VA=首帧锚定；FL2VA=首尾帧路径；L2VA=尾帧收敛；R2V=全参考重写"}),
            "operation": (H3_OPERATIONS, {"default": "generate",
                                          "tooltip": "generate=生成；rewrite=改写；convert_storyboard=分镜转换；audit=审计；repair=修复"}),
            "duration": ("FLOAT", {"default": 10.0, "min": 0.5, "max": 600.0,
                                   "tooltip": "目标视频时长（秒），决定首行对齐指令的 S.SS 与镜头时间戳"}),
        }, "optional": {
            "storyboard": (types.STORYBOARD,),
            "character_bible": (types.CHARACTER_BIBLE,),
            "reference_manifest": (types.REFERENCE_MANIFEST,),
            "images": ("IMAGE", {"tooltip": "首/尾帧参考图（I2VA/FL2VA/L2VA 使用）"}),
        }}

    RETURN_TYPES = ("STRING", types.H3_PROMPT_PLAN, types.REFERENCE_MANIFEST, "STRING", "STRING")
    RETURN_NAMES = ("prompt", "H3_PROMPT_PLAN", "REFERENCE_MANIFEST", "validation", "warnings")
    FUNCTION = "direct"
    CATEGORY = "AI Prompt Studio"
    DESCRIPTION = "按官方手册生成/改写/转换/审计/修复 MiniMax H3 提示词（输出 STRING 直连核心 H3 节点）。"

    def direct(self, AI_PROFILE, text, mode, operation, duration,
               storyboard=None, character_bible=None, reference_manifest=None, images=None):
        plan = H3PromptPlan(mode=mode, operation=operation, duration_seconds=duration)
        plan.warnings.append("MiniMax H3 Director 功能将在 Phase 5 实现（renderer + validator + repair）")
        from ..schemas.references import ReferenceManifest

        manifest = ReferenceManifest.from_json(reference_manifest) if reference_manifest else ReferenceManifest()
        return ("", plan.to_json(), manifest.to_json(), plan.validation.as_text(),
                "\n".join(plan.warnings))

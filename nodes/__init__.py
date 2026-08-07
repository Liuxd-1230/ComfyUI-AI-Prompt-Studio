"""nodes：9 个 AI Prompt Studio 节点。"""

from .character_bible import APS_CharacterBible
from .llm_chat import APS_LLMGenerate
from .minimax_h3_director import APS_MiniMaxH3Director
from .model_profile import APS_ModelProfile
from .prompt_composer import APS_PromptComposer
from .reference_analyzer import APS_ReferenceAnalyzer
from .runtime_control import APS_RuntimeControl
from .storyboard_builder import APS_StoryboardBuilder
from .storyboard_select import APS_StoryboardSelect

NODE_CLASSES = [
    APS_ModelProfile,
    APS_LLMGenerate,
    APS_ReferenceAnalyzer,
    APS_CharacterBible,
    APS_StoryboardBuilder,
    APS_StoryboardSelect,
    APS_PromptComposer,
    APS_MiniMaxH3Director,
    APS_RuntimeControl,
]

__all__ = [c.__name__ for c in NODE_CLASSES] + ["NODE_CLASSES"]

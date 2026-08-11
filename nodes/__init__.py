"""AI Prompt Studio 节点集合。"""

from .character_bible import APS_CharacterBible
from .llm_chat import APS_LLMGenerate
from .h3_prompt_studio import APS_H3PromptStudio
from .model_profile import APS_ModelProfile
from .prompt_studio import APS_PromptStudio
from .reference_analyzer import APS_ReferenceAnalyzer
from .reference_prompt import APS_ReferencePrompt
from .runtime_control import APS_RuntimeControl
from .storyboard_builder import APS_StoryboardBuilder
from .storyboard_select import APS_StoryboardSelect
from .unload_model import APS_UnloadModel

NODE_CLASSES = [
    APS_ModelProfile,
    APS_LLMGenerate,
    APS_ReferenceAnalyzer,
    APS_ReferencePrompt,
    APS_CharacterBible,
    APS_StoryboardBuilder,
    APS_StoryboardSelect,
    APS_PromptStudio,
    APS_H3PromptStudio,
    APS_RuntimeControl,
    APS_UnloadModel,
]

__all__ = [c.__name__ for c in NODE_CLASSES] + ["NODE_CLASSES"]

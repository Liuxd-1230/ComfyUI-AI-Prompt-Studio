"""统一中间数据结构（schemas 包）。

所有节点间传递的数据都必须经过这里的数据类（见 docs/adr/0001-dataclass-schemas.md）。
"""

from .base import SCHEMA_VERSION, Schema, SchemaError, to_json
from .character import (
    MERGE_STRATEGIES,
    TRAIT_CATEGORIES,
    CharacterBible,
    CharacterBook,
    CharacterCandidate,
    CharacterConflict,
    CharacterTrait,
)
from .h3 import (
    H3_MODES,
    H3_OPERATIONS,
    R2V_SECTIONS,
    THREE_FIELDS,
    H3Asset,
    H3AudioField,
    H3Dialogue,
    H3PromptPlan,
    H3Retention,
    H3Shot,
    H3Speaker,
    H3Subject,
)
from .profile import (
    PROTOCOLS,
    PROVIDERS,
    REASONING_LEVELS,
    UNLOAD_POLICIES,
    WEB_SEARCH_POLICIES,
    AIProfile,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
)
from .prompt_plan import (
    ANIMA_VARIANTS,
    COMPOSER_OPERATIONS,
    PROMPT_MODES,
    TARGET_FAMILIES,
    GenerationProfile,
    PromptPlan,
    ValidationIssue,
    ValidationReport,
    empty_validation,
)
from .prompt_session import PromptRevision, PromptSession
from .references import (
    ANALYSIS_MODES,
    ASSET_TYPES,
    AssetRef,
    ReferenceAnalysis,
    ReferenceManifest,
    SubjectRef,
)
from .results import (
    ERROR_KINDS,
    ChatMessage,
    ChatSession,
    Citation,
    ErrorInfo,
    LLMResult,
    ToolCall,
    Usage,
    empty_llm_result,
    make_error,
)
from .storyboard import (
    SELECT_MODES,
    SPLIT_MODES,
    Beat,
    ContinuityNote,
    Scene,
    Shot,
    StoryItem,
    StoryItemList,
    Storyboard,
)
from .types import (
    AI_PROFILE,
    CHAT_SESSION,
    CHARACTER_BIBLE,
    CHARACTER_CANDIDATE,
    GENERATION_PROFILE,
    H3_PROMPT_PLAN,
    LLM_RESULT,
    PROMPT_PLAN,
    PROMPT_SESSION,
    REFERENCE_ANALYSIS,
    REFERENCE_MANIFEST,
    STORYBOARD,
    STORY_ITEM,
    STORY_ITEM_LIST,
    schema_class_for,
)

__all__ = [
    "SCHEMA_VERSION", "Schema", "SchemaError", "to_json",
    # types
    "AI_PROFILE", "LLM_RESULT", "CHAT_SESSION", "REFERENCE_ANALYSIS",
    "CHARACTER_CANDIDATE", "REFERENCE_MANIFEST", "CHARACTER_BIBLE",
    "STORYBOARD", "STORY_ITEM", "STORY_ITEM_LIST", "PROMPT_PLAN", "PROMPT_SESSION",
    "GENERATION_PROFILE", "H3_PROMPT_PLAN", "schema_class_for",
    # profile
    "AIProfile", "DEFAULT_BASE_URL", "DEFAULT_MODEL",
    "PROTOCOLS", "PROVIDERS", "REASONING_LEVELS", "WEB_SEARCH_POLICIES", "UNLOAD_POLICIES",
    # results
    "LLMResult", "ChatSession", "ChatMessage", "Citation", "ToolCall", "Usage",
    "ErrorInfo", "ERROR_KINDS", "empty_llm_result", "make_error",
    # character
    "CharacterTrait", "CharacterCandidate", "CharacterBible", "CharacterBook",
    "CharacterConflict", "TRAIT_CATEGORIES", "MERGE_STRATEGIES",
    # references
    "ReferenceAnalysis", "ReferenceManifest", "AssetRef", "SubjectRef",
    "ANALYSIS_MODES", "ASSET_TYPES",
    # storyboard
    "Storyboard", "Scene", "Shot", "Beat", "StoryItem", "StoryItemList",
    "ContinuityNote", "SPLIT_MODES", "SELECT_MODES",
    # prompt_plan
    "PromptPlan", "GenerationProfile", "ValidationReport", "ValidationIssue",
    "empty_validation", "TARGET_FAMILIES", "ANIMA_VARIANTS", "PROMPT_MODES", "COMPOSER_OPERATIONS",
    "PromptSession", "PromptRevision",
    # h3
    "H3PromptPlan", "H3Shot", "H3Speaker", "H3Subject", "H3Asset",
    "H3Dialogue", "H3Retention", "H3AudioField",
    "H3_MODES", "H3_OPERATIONS", "R2V_SECTIONS", "THREE_FIELDS",
]

"""AI Profile：LLM 服务的命名配置（密钥永远不进入本结构，只有引用 id）。"""


import dataclasses
from typing import Any, Dict, Optional

from .base import Schema

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"

# 合法枚举（供节点 combo 复用）
PROTOCOLS = ["auto", "responses", "chat_completions"]
REASONING_LEVELS = ["off", "low", "medium", "high"]
WEB_SEARCH_POLICIES = ["off", "auto", "always"]
UNLOAD_POLICIES = ["never", "after_request", "after_success"]
PROVIDERS = ["deepseek", "openai_compatible", "local"]


@dataclasses.dataclass
class AIProfile(Schema):
    """一个命名 LLM 服务档案。密钥存放在 SecretStore，此处仅存 api_key_ref。"""

    profile_id: str = ""
    name: str = ""
    provider: str = "deepseek"
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    protocol: str = "auto"          # auto | responses | chat_completions
    reasoning: str = "high"         # off | low | medium | high
    web_search: str = "auto"        # off | auto | always
    unload_policy: str = "never"    # never | after_request | after_success
    vision_base_url: str = ""
    vision_model: str = ""
    api_key_ref: str = ""           # 指向 SecretStore 的键名，不是密钥本身
    capabilities: Dict[str, Any] = dataclasses.field(default_factory=dict)
    runtime: Dict[str, Any] = dataclasses.field(default_factory=dict)
    timeout: float = 120.0
    max_retries: int = 1
    # ---- 高级采样参数（产品决策 D19：不进普通节点 UI，只在档案高级设置配置；
    #       None = 不发送该字段，交给 provider 默认值）----
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    max_tokens: Optional[int] = None
    # ---- 附件能力（D20）：用户断言端点支持时手动开启（覆盖能力探测的保守判定）----
    supports_vision: bool = False
    supports_files: bool = False
    created_at: str = ""
    updated_at: str = ""
    notes: str = ""

    def validate(self) -> list[str]:
        problems = []
        if not self.profile_id:
            problems.append("AIProfile: profile_id 不能为空")
        if self.protocol not in PROTOCOLS:
            problems.append(f"AIProfile: 非法 protocol {self.protocol!r}")
        if self.reasoning not in REASONING_LEVELS:
            problems.append(f"AIProfile: 非法 reasoning {self.reasoning!r}")
        if self.web_search not in WEB_SEARCH_POLICIES:
            problems.append(f"AIProfile: 非法 web_search {self.web_search!r}")
        if self.unload_policy not in UNLOAD_POLICIES:
            problems.append(f"AIProfile: 非法 unload_policy {self.unload_policy!r}")
        if not self.base_url:
            problems.append("AIProfile: base_url 不能为空")
        return problems

    def node_payload(self) -> Dict[str, Any]:
        """节点图中流转的 AI_PROFILE dict：不含 api_key_ref（纵深防御，密钥位置也不外泄）。"""
        data = self.to_json()
        data.pop("api_key_ref", None)
        return data

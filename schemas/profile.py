"""AI Profile：LLM 服务的命名配置（密钥永远不进入本结构，只有引用 id）。"""


import dataclasses
from typing import Any, Dict, Optional
from urllib.parse import urlparse

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
    # ---- 视觉/文本 Profile 解耦（P1/D）：视觉分析可指向另一档案 ----
    # 留空 = 用本档案的 vision_base_url/vision_model；填写 = 用该档案的
    # vision_base_url/vision_model/api_key（文本生成仍用本档案 base_url/model）。
    vision_profile_id: str = ""
    # ---- 外部搜索后端（C4）：无原生 web_search 时经该端点注入联网结果 ----
    search_url: str = ""
    created_at: str = ""
    updated_at: str = ""
    notes: str = ""

    def validate(self) -> list[str]:
        problems = []
        if not self.profile_id:
            problems.append("AIProfile: profile_id 不能为空")
        if self.provider not in PROVIDERS:
            problems.append(f"AIProfile: 非法 provider {self.provider!r}")
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
        elif urlparse(self.base_url).scheme not in ("http", "https"):
            problems.append("AIProfile: base_url 必须是 http(s) URL")
        if not self.model.strip():
            problems.append("AIProfile: model 不能为空")
        if self.vision_base_url and urlparse(self.vision_base_url).scheme not in ("http", "https"):
            problems.append("AIProfile: vision_base_url 必须是 http(s) URL")
        if self.search_url and urlparse(self.search_url).scheme not in ("http", "https"):
            problems.append("AIProfile: search_url 必须是 http(s) URL")
        if self.vision_profile_id and self.vision_profile_id == self.profile_id:
            problems.append("AIProfile: vision_profile_id 不能指向自身")
        if not 1 <= float(self.timeout) <= 600:
            problems.append("AIProfile: timeout 必须在 1..600 秒")
        if not 0 <= int(self.max_retries) <= 10:
            problems.append("AIProfile: max_retries 必须在 0..10")
        if self.max_tokens is not None and not 1 <= int(self.max_tokens) <= 1_000_000:
            problems.append("AIProfile: max_tokens 必须为正整数")
        for name, value, lo, hi in (
            ("temperature", self.temperature, 0.0, 2.0),
            ("top_p", self.top_p, 0.0, 1.0),
            ("frequency_penalty", self.frequency_penalty, -2.0, 2.0),
            ("presence_penalty", self.presence_penalty, -2.0, 2.0),
        ):
            if value is not None and not lo <= float(value) <= hi:
                problems.append(f"AIProfile: {name} 必须在 {lo}..{hi}")
        return problems

    def node_payload(self) -> Dict[str, Any]:
        """节点图中流转的 AI_PROFILE dict：不含 api_key_ref（纵深防御，密钥位置也不外泄）。"""
        data = self.to_json()
        data.pop("api_key_ref", None)
        return data

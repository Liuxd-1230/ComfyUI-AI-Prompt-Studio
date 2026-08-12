"""提示词计划与生成档案：PromptPlan / GenerationProfile / ValidationReport。"""


import dataclasses
import time
from typing import Any, Dict, List

from .base import Schema

TARGET_FAMILIES = ["anima", "z_image", "qwen_image_edit", "generic_image", "sdxl", "flux"]
ANIMA_VARIANTS = ["base", "aesthetic", "turbo"]
PROMPT_MODES = ["tags", "natural_language", "hybrid"]
COMPOSER_OPERATIONS = ["generate", "expand", "rewrite", "translate", "audit", "repair", "convert"]


@dataclasses.dataclass
class ValidationIssue(Schema):
    """一条校验问题。"""

    severity: str = "warning"       # error | warning | info
    code: str = ""
    message: str = ""
    location: str = ""


@dataclasses.dataclass
class ValidationReport(Schema):
    """校验报告：聚合多个问题。"""

    valid: bool = True
    issues: List[ValidationIssue] = dataclasses.field(default_factory=list)
    checks: List[str] = dataclasses.field(default_factory=list)

    def add(self, severity: str, code: str, message: str, location: str = "") -> None:
        self.issues.append(ValidationIssue(severity=severity, code=code, message=message, location=location))
        if severity == "error":
            self.valid = False

    def summary(self) -> str:
        errors = sum(1 for i in self.issues if i.severity == "error")
        warnings = sum(1 for i in self.issues if i.severity == "warning")
        status = "通过" if self.valid else "未通过"
        return f"{status}（error={errors}, warning={warnings}）"

    def as_text(self) -> str:
        lines = [self.summary()]
        for i in self.issues:
            loc = f" @{i.location}" if i.location else ""
            lines.append(f"  [{i.severity}] {i.code}{loc}: {i.message}")
        return "\n".join(lines)


def empty_validation() -> ValidationReport:
    return ValidationReport()


@dataclasses.dataclass
class PromptPlan(Schema):
    """面向目标图像模型的中间计划（正负提示词 + 绑定 + 校验）。"""

    plan_id: str = ""
    target_family: str = "anima"    # anima | generic_image | sdxl | flux
    target_variant: str = "base"    # base | aesthetic | turbo（或自定义）
    operation: str = "generate"
    prompt_mode: str = "tags"       # tags | natural_language | hybrid
    positive: str = ""
    negative: str = ""
    character_bindings: List[Dict[str, Any]] = dataclasses.field(default_factory=list)  # {character, attributes}
    tags: List[str] = dataclasses.field(default_factory=list)
    lora_triggers: List[str] = dataclasses.field(default_factory=list)
    warnings: List[str] = dataclasses.field(default_factory=list)
    validation: ValidationReport = dataclasses.field(default_factory=empty_validation)
    created_at: str = ""

    def __post_init__(self):
        import uuid

        if not self.plan_id:
            self.plan_id = "pp_" + uuid.uuid4().hex[:10]
        if not self.created_at:
            self.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")


@dataclasses.dataclass
class GenerationProfile(Schema):
    """目标图像模型的采样参数建议。"""

    target_family: str = "anima"
    target_variant: str = "base"
    steps: int = 30
    cfg: float = 5.0
    sampler: str = ""
    scheduler: str = ""
    clip_skip: int = -1
    resolution: str = ""
    notes: str = ""
    extra: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def as_text(self) -> str:
        parts = [f"steps={self.steps}", f"cfg={self.cfg}"]
        if self.sampler:
            parts.append(f"sampler={self.sampler}")
        if self.scheduler:
            parts.append(f"scheduler={self.scheduler}")
        return ", ".join(parts)

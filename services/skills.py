"""Prompt Skill 系统：内置只读 YAML 技能（id/version/target/renderer/system_prompt/validators/source/hash）。

技能用于 Composer 的 LLM 操作（expand/rewrite/translate/repair/custom_skill）。
内置技能在仓库 skills/ 下，只读不写；hash 用于内容审计。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


@dataclass
class Skill:
    id: str
    version: str
    target_family: str
    target_variant: str
    renderer: str
    system_prompt: str
    validators: List[str] = field(default_factory=list)
    source: str = "builtin"
    description: str = ""
    hash: str = ""

    def compute_hash(self) -> str:
        payload = f"{self.id}:{self.version}:{self.system_prompt}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


_CACHE: Optional[Dict[str, Skill]] = None


def load_skills() -> Dict[str, Skill]:
    """加载 skills/*.yaml（内置只读）。解析失败跳过并警告。"""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    import logging
    import yaml

    logger = logging.getLogger("ai_prompt_studio.skills")
    skills: Dict[str, Skill] = {}
    if not SKILLS_DIR.is_dir():
        _CACHE = skills
        return skills
    for path in sorted(SKILLS_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            skill = Skill(
                id=str(data.get("id", path.stem)),
                version=str(data.get("version", "1.0")),
                target_family=str(data.get("target_family", "generic_image")),
                target_variant=str(data.get("target_variant", "")),
                renderer=str(data.get("renderer", "generic")),
                system_prompt=str(data.get("system_prompt", "")),
                validators=list(data.get("validators", []) or []),
                source=str(data.get("source", "builtin")),
                description=str(data.get("description", "")),
            )
            skill.hash = skill.compute_hash()
            skills[skill.id] = skill
        except Exception as exc:  # noqa: BLE001 - 单个技能损坏不阻塞
            logger.warning("技能加载失败 %s: %s", path.name, exc)
    _CACHE = skills
    return skills


def get_skill(skill_id: str) -> Optional[Skill]:
    return load_skills().get(skill_id)


def list_skill_ids() -> List[str]:
    return sorted(load_skills().keys())

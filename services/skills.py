"""Prompt Skill 系统：内置只读 YAML 技能 + 用户自定义技能（可增删改、启用/停用）。

技能用于 Prompt Studio 的目标策略与 H3 规划策略。
- 内置技能：仓库 skills/ 下，只读（source=builtin）；
- 自定义技能：用户配置目录 skills/ 下（source=custom），支持创建/复制/编辑/删除/启停；
- 同名时自定义技能覆盖内置（优先级：custom > builtin）；
- hash 用于内容审计；validators 在保存时做基本校验（白名单字段、必填项）。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from ..server.config_store import default_config_dir

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"

# 允许写入自定义技能的字段（白名单，防止任意属性注入）
SKILL_FIELDS = ["id", "version", "target_family", "target_variant", "renderer",
                "system_prompt", "validators", "description"]
# 允许的 renderer / target_family（避免保存出 Composer 无法消费的技能）
ALLOWED_RENDERERS = {"generic", "anima_plan", "anima_tags", "minimax_h3", "z_image", "qwen_image_edit"}
ALLOWED_FAMILIES = {"generic_image", "anima", "minimax_h3", "z_image", "qwen_image_edit"}
ALLOWED_VALIDATORS = {"anima", "special_image", "minimax_h3"}
REQUIRED_FIELDS = ["system_prompt", "renderer"]


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
    enabled: bool = True
    hash: str = ""
    path: str = ""

    def compute_hash(self) -> str:
        payload = json.dumps({
            "id": self.id, "version": self.version,
            "target_family": self.target_family,
            "target_variant": self.target_variant,
            "renderer": self.renderer,
            "system_prompt": self.system_prompt,
            "validators": self.validators,
            "description": self.description,
            "enabled": self.enabled,
        }, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


_CACHE: Optional[Dict[str, Skill]] = None


def custom_skills_dir() -> Path:
    """用户自定义技能目录（默认配置目录下的 skills/）。"""
    return default_config_dir() / "skills"


def _load_file(path: Path, source: str) -> Optional[Skill]:
    """从单个 YAML 文件加载技能；损坏返回 None。"""
    import logging
    import yaml

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            return None
        data = {**data, "id": str(data.get("id", path.stem))}
        problems = validate_skill_payload(data)
        if problems:
            raise ValueError("；".join(problems))
        skill = Skill(
            id=str(data.get("id", path.stem)),
            version=str(data.get("version", "1.0")),
            target_family=str(data.get("target_family", "generic_image")),
            target_variant=str(data.get("target_variant", "")),
            renderer=str(data.get("renderer", "generic")),
            system_prompt=str(data.get("system_prompt", "")),
            validators=list(data.get("validators", []) or []),
            # 来源由加载目录决定，不能信任 YAML 自报为 builtin 绕过写保护。
            source=source,
            description=str(data.get("description", "")),
            enabled=bool(data.get("enabled", True)),
            path=str(path.resolve()),
        )
        skill.hash = skill.compute_hash()
        return skill
    except Exception as exc:  # noqa: BLE001 - 单个技能损坏不阻塞
        logging.getLogger("ai_prompt_studio.skills").warning(
            "技能加载失败 %s: %s", path.name, exc)
        return None


def load_skills() -> Dict[str, Skill]:
    """加载内置 + 自定义技能（自定义同名覆盖内置）。"""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    skills: Dict[str, Skill] = {}
    if SKILLS_DIR.is_dir():
        for path in sorted(SKILLS_DIR.rglob("*.yaml")):
            skill = _load_file(path, "builtin")
            if skill is not None:
                skills[skill.id] = skill
    cdir = custom_skills_dir()
    if cdir.is_dir():
        for path in sorted(cdir.rglob("*.yaml")):
            skill = _load_file(path, "custom")
            if skill is not None:
                skills[skill.id] = skill  # 自定义覆盖内置
    _CACHE = skills
    return skills


def reset_cache() -> None:
    """测试/配置变更后清缓存。"""
    global _CACHE
    _CACHE = None


def get_skill(skill_id: str) -> Optional[Skill]:
    skill = load_skills().get(skill_id)
    return skill if skill is not None and skill.enabled else None


def list_skill_ids() -> List[str]:
    return sorted(load_skills().keys())


# ------------------------------------------------------------------ 管理 API

def list_skill_records() -> List[Dict]:
    """列出全部技能（含来源/版本/启用状态/hash），供设置面板与管理路由。"""
    return [{"id": s.id, "version": s.version, "source": s.source,
             "enabled": s.enabled, "target_family": s.target_family,
             "renderer": s.renderer, "description": s.description,
             "hash": s.hash, "system_prompt": s.system_prompt[:120]}
            for s in load_skills().values()]


def get_skill_record(skill_id: str) -> Optional[Dict]:
    s = load_skills().get(skill_id)
    if s is None:
        return None
    return {"id": s.id, "version": s.version, "source": s.source,
            "enabled": s.enabled, "target_family": s.target_family,
            "target_variant": s.target_variant, "renderer": s.renderer,
            "system_prompt": s.system_prompt, "validators": s.validators,
            "description": s.description, "hash": s.hash}


def validate_skill_payload(data: Dict, require_id: bool = True) -> List[str]:
    """校验技能 payload（白名单字段 + 必填项 + 枚举），返回问题列表。"""
    problems = []
    if require_id:
        sid = str(data.get("id", "")).strip()
        if not sid:
            problems.append("技能缺少 id")
        elif not re_fullmatch(r"[A-Za-z0-9_\-]+", sid):
            problems.append("技能 id 只允许字母/数字/下划线/连字符")
    for f in REQUIRED_FIELDS:
        if not str(data.get(f, "")).strip():
            problems.append(f"技能缺少必填字段 {f}")
    renderer = str(data.get("renderer", ""))
    if renderer and renderer not in ALLOWED_RENDERERS:
        problems.append(f"renderer {renderer!r} 不受支持（可选：{', '.join(sorted(ALLOWED_RENDERERS))}）")
    family = str(data.get("target_family", ""))
    if family and family not in ALLOWED_FAMILIES:
        problems.append(f"target_family {family!r} 不受支持（可选：{', '.join(sorted(ALLOWED_FAMILIES))}）")
    validators = data.get("validators", []) or []
    if not isinstance(validators, list):
        problems.append("validators 必须是字符串数组")
    else:
        unknown_validators = {str(v) for v in validators} - ALLOWED_VALIDATORS
        if unknown_validators:
            problems.append(f"不受支持的 validators：{', '.join(sorted(unknown_validators))}")
    unknown = set(data) - set(SKILL_FIELDS) - {"enabled", "source"}
    if unknown:
        problems.append(f"未知字段被忽略：{', '.join(sorted(unknown))}")
    return problems


def copy_builtin_to_custom(skill_id: str) -> Dict:
    """把内置技能复制为自定义（同名自定义覆盖内置）。"""
    s = load_skills().get(skill_id)
    if s is None or s.source != "builtin":
        raise KeyError(f"内置技能不存在: {skill_id}")
    payload = {"id": s.id, "version": s.version, "target_family": s.target_family,
               "target_variant": s.target_variant, "renderer": s.renderer,
               "system_prompt": s.system_prompt, "validators": list(s.validators),
               "description": s.description, "enabled": True}
    return _write_custom(payload)


def create_custom_skill(payload: Dict) -> Dict:
    """新建自定义技能。"""
    problems = validate_skill_payload(payload)
    if problems:
        raise ValueError("；".join(problems))
    return _write_custom(payload)


def update_custom_skill(skill_id: str, payload: Dict) -> Dict:
    """更新自定义技能（builtin 只读，不允许覆盖内置文件）。"""
    s = load_skills().get(skill_id)
    if s is None or s.source != "custom":
        raise KeyError(f"自定义技能不存在: {skill_id}")
    payload = {**payload, "id": skill_id}
    problems = validate_skill_payload(payload)
    if problems:
        raise ValueError("；".join(problems))
    return _write_custom(payload)


def delete_custom_skill(skill_id: str) -> None:
    """删除自定义技能（builtin 只读）。"""
    s = load_skills().get(skill_id)
    if s is None:
        raise KeyError(f"技能不存在: {skill_id}")
    if s.source != "custom":
        raise ValueError(f"内置技能 {skill_id} 只读，不允许删除（可复制为自定义后修改）")
    path = _custom_skill_path(s)
    if path.exists():
        path.unlink()
    reset_cache()


def set_skill_enabled(skill_id: str, enabled: bool) -> Dict:
    """启用/停用技能（自定义可改；内置只读时提示可复制后修改）。"""
    s = load_skills().get(skill_id)
    if s is None:
        raise KeyError(f"技能不存在: {skill_id}")
    if s.source != "custom":
        raise ValueError(f"内置技能 {skill_id} 只读，停用请先复制为自定义")
    path = _custom_skill_path(s)
    if not path.exists():
        raise KeyError(f"自定义技能文件不存在: {skill_id}")
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data["enabled"] = bool(enabled)
    _atomic_write(path, data)
    reset_cache()
    return get_skill_record(skill_id) or {}


def _write_custom(payload: Dict) -> Dict:
    """把 payload 写入自定义技能 YAML（白名单字段 + 强制 source=custom）。"""
    import yaml

    cdir = custom_skills_dir()
    cdir.mkdir(parents=True, exist_ok=True)
    sid = str(payload.get("id", "")).strip()
    if not sid:
        raise ValueError("技能缺少 id")
    clean = {k: payload.get(k) for k in SKILL_FIELDS if k in payload}
    clean["source"] = "custom"
    clean["enabled"] = bool(payload.get("enabled", True))
    path = cdir / f"{sid}.yaml"
    _atomic_write(path, clean)
    reset_cache()
    return get_skill_record(sid) or {}


def _custom_skill_path(skill: Skill) -> Path:
    """返回实际加载路径；递归目录里的自定义 Skill 也能被管理。"""
    base = custom_skills_dir().resolve()
    path = Path(skill.path).resolve() if skill.path else (base / f"{skill.id}.yaml")
    if path != base and base not in path.parents:
        raise ValueError("自定义技能路径越出配置目录")
    return path


def _atomic_write(path: Path, data: dict) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def re_fullmatch(pattern: str, value: str) -> bool:
    import re

    return re.fullmatch(pattern, value) is not None

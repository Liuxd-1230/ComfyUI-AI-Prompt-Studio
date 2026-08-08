"""AI Prompt Studio 后端路由。

处理器函数（handle_*）不依赖 aiohttp，可直接单元测试；
register_routes() 在 ComfyUI 内把处理器挂到 PromptServer.instance.routes。
所有路由同时有 /api 前缀副本（ComfyUI add_routes 自动注册）。
"""
from __future__ import annotations

import asyncio
import json
import logging
from functools import partial
from typing import Any, Callable, Dict, Optional

from ..schemas.profile import AIProfile
from ..services import capability_probe
from .config_store import ConfigStore, get_store

logger = logging.getLogger("ai_prompt_studio.routes")

API_PREFIX = "/ai_prompt_studio"


# ---------------------------------------------------------------- 处理器（可测）

def _profile_public(profile: AIProfile, store: ConfigStore) -> Dict[str, Any]:
    data = profile.to_json()
    data["api_key_masked"] = store.masked_api_key(profile.profile_id)
    data["has_api_key"] = store.has_api_key(profile.profile_id)
    data["capabilities"] = store.get_capabilities(profile.profile_id)
    return data


def handle_status(store: ConfigStore) -> Dict[str, Any]:
    import importlib.metadata as _md

    version = "0.1.0"
    try:
        version = _md.version("comfyui-ai-prompt-studio")
    except Exception:  # noqa: BLE001
        pass

    comfyui_version = None
    try:
        import comfyui_version  # type: ignore  # 仅 ComfyUI 运行时存在

        comfyui_version = getattr(comfyui_version, "__version__", None)
    except Exception:  # noqa: BLE001
        pass

    return {
        "name": "AI Prompt Studio",
        "version": version,
        "comfyui_version": comfyui_version,
        "config_dir": str(store.config_dir()),
        "anima_booster_detected": detect_anima_booster(),
        "profile_count": len(store.list_profiles()),
        "api_prefix": API_PREFIX,
    }


def detect_anima_booster() -> Optional[bool]:
    """软检测 ANIMA_BOOSTER（存在性提示，无硬依赖）。"""
    try:
        import os

        import folder_paths  # type: ignore

        for base in folder_paths.get_folder_paths("custom_nodes"):
            try:
                names = os.listdir(base)
            except OSError:
                continue
            for n in names:
                if "anima" in n.lower():
                    return True
        return False
    except Exception:  # noqa: BLE001
        return None


def handle_list_profiles(store: ConfigStore) -> Dict[str, Any]:
    profiles = store.list_profiles()
    for profile in profiles:
        profile["capabilities"] = store.get_capabilities(profile["profile_id"])
    return {"profiles": profiles, "default_profile_id": store._config.get("default_profile_id", "")}


def handle_get_profile(profile_id: str, store: ConfigStore) -> Dict[str, Any]:
    profile = store.get_profile(profile_id)
    if profile is None:
        raise KeyError(f"profile 不存在: {profile_id}")
    return _profile_public(profile, store)


def handle_create_profile(payload: Dict[str, Any], store: ConfigStore) -> Dict[str, Any]:
    profile = store.create_profile(payload)
    return _profile_public(profile, store)


def handle_update_profile(profile_id: str, payload: Dict[str, Any], store: ConfigStore) -> Dict[str, Any]:
    profile = store.update_profile(profile_id, payload)
    return _profile_public(profile, store)


def handle_delete_profile(profile_id: str, store: ConfigStore) -> Dict[str, Any]:
    store.delete_profile(profile_id)
    return {"ok": True, "profile_id": profile_id}


def handle_set_api_key(profile_id: str, payload: Dict[str, Any], store: ConfigStore) -> Dict[str, Any]:
    key = str(payload.get("api_key", "") or "").strip()
    if not key:
        raise ValueError("api_key 不能为空")
    store.set_api_key(profile_id, key)
    return {"ok": True, "masked": store.masked_api_key(profile_id),
            "has_api_key": store.has_api_key(profile_id)}


def handle_clear_api_key(profile_id: str, store: ConfigStore) -> Dict[str, Any]:
    store.delete_api_key(profile_id)
    return {"ok": True, "has_api_key": False}


def handle_probe(profile_id: str, store: ConfigStore) -> Dict[str, Any]:
    """手动执行能力探测并写缓存。"""
    profile = store.get_profile(profile_id)
    if profile is None:
        raise KeyError(f"profile 不存在: {profile_id}")
    api_key = store.get_api_key(profile_id) or ""
    vision_profile = None
    vision_api_key = ""
    if profile.vision_profile_id:
        vision_profile = store.get_profile(profile.vision_profile_id)
        if vision_profile is not None:
            vision_api_key = store.get_api_key(vision_profile.profile_id) or ""
    caps = capability_probe.probe_profile(
        profile, api_key, vision_profile=vision_profile,
        vision_api_key=vision_api_key)
    if profile.vision_profile_id and vision_profile is None:
        caps["vision_service"] = False
        caps["vision_model_available"] = False
        caps.setdefault("checks", {})["vision_service"] = {
            "ok": False, "endpoint": "", "http_status": 0,
            "detail": f"视觉档案 {profile.vision_profile_id!r} 不存在",
        }
    profile_updates: Dict[str, Any] = {}
    resolved_base = str(caps.get("resolved_base_url", "") or "").rstrip("/")
    if resolved_base and resolved_base != profile.base_url.rstrip("/"):
        profile_updates["base_url"] = resolved_base
    # 手动开关只是在尚未探测时的声明。真实多模态探针跑过后，以实测结果
    # 回写勾选状态，避免 UI 显示支持而 Gateway 继续发送必失败的附件。
    if "chat_completions" in caps.get("checks", {}):
        profile_updates.update(
            supports_vision=bool(caps.get("vision")),
            supports_files=bool(caps.get("files")),
        )
    if profile_updates:
        store.update_profile(profile_id, profile_updates)
    if caps.get("error"):
        # 失败结果也覆盖旧缓存，避免设置页/网关继续使用上一次的成功能力。
        store.set_capabilities(profile_id, caps)
        store.append_request_log({
            "profile_id": profile_id, "kind": "probe", "ok": False,
            "detail": caps.get("error", "capability probe failed"),
        })
        return {"ok": False, "profile_id": profile_id, **caps}
    # 手动“重新探测”必须替换旧结果；保留旧 True 会让 unknown 永久伪装成支持。
    store.set_capabilities(profile_id, caps)
    store.append_request_log({"profile_id": profile_id, "kind": "probe", "ok": True, "detail": "capability probe ok"})
    return {"ok": True, "profile_id": profile_id, **caps}


def handle_capabilities(profile_id: Optional[str], store: ConfigStore) -> Dict[str, Any]:
    if profile_id:
        return {"profile_id": profile_id, "capabilities": store.get_capabilities(profile_id)}
    return {"capabilities": {p["profile_id"]: store.get_capabilities(p["profile_id"])
                              for p in store.list_profiles()}}


def handle_test(profile_id: str, store: ConfigStore) -> Dict[str, Any]:
    """轻量连接测试（不写能力缓存）。"""
    profile = store.get_profile(profile_id)
    if profile is None:
        raise KeyError(f"profile 不存在: {profile_id}")
    api_key = store.get_api_key(profile_id) or ""
    caps = capability_probe.probe_profile(profile, api_key, exhaustive=False)
    store.append_request_log({
        "profile_id": profile_id, "kind": "test", "ok": caps.get("auth_ok", False),
        "detail": caps.get("error") or f"auth ok, models={len(caps.get('models', []))}",
    })
    return {"ok": caps.get("auth_ok", False), "profile_id": profile_id, **caps}


def handle_log(store: ConfigStore) -> Dict[str, Any]:
    return {"log": store.get_request_log(limit=100)}


def handle_settings_get(store: ConfigStore) -> Dict[str, Any]:
    return {"settings": store.get_settings()}


def handle_settings_set(payload: Dict[str, Any], store: ConfigStore) -> Dict[str, Any]:
    store.set_settings(dict(payload.get("settings", {}) or {}))
    return {"ok": True}


def handle_runtime(payload: Dict[str, Any], store: ConfigStore) -> Dict[str, Any]:
    """本地运行时操作：调用与 Runtime Control 节点相同的服务层
    （services/runtime/control.run_runtime_action），Settings /runtime 与节点共用实现。"""
    from ..services.runtime.control import run_runtime_action
    return run_runtime_action(
        str(payload.get("backend", "")),
        str(payload.get("action", "status")),
        str(payload.get("url", "")),
        str(payload.get("model", "")),
    )


# ---------------------------------------------------------------- Prompt Skill 管理

def handle_skills_list(store: ConfigStore) -> Dict[str, Any]:
    from ..services import skills as skills_svc
    return {"skills": skills_svc.list_skill_records()}


def handle_skill_get(skill_id: str, store: ConfigStore) -> Dict[str, Any]:
    from ..services import skills as skills_svc
    rec = skills_svc.get_skill_record(skill_id)
    if rec is None:
        raise KeyError(f"技能不存在: {skill_id}")
    return rec


def handle_skill_create(payload: Dict[str, Any], store: ConfigStore) -> Dict[str, Any]:
    from ..services import skills as skills_svc
    if payload.get("copy_from"):
        return skills_svc.copy_builtin_to_custom(str(payload["copy_from"]))
    return skills_svc.create_custom_skill(dict(payload or {}))


def handle_skill_update(skill_id: str, payload: Dict[str, Any], store: ConfigStore) -> Dict[str, Any]:
    from ..services import skills as skills_svc
    return skills_svc.update_custom_skill(skill_id, dict(payload or {}))


def handle_skill_delete(skill_id: str, store: ConfigStore) -> Dict[str, Any]:
    from ..services import skills as skills_svc
    skills_svc.delete_custom_skill(skill_id)
    return {"ok": True, "skill_id": skill_id}


def handle_skill_set_enabled(skill_id: str, payload: Dict[str, Any], store: ConfigStore) -> Dict[str, Any]:
    from ..services import skills as skills_svc
    return skills_svc.set_skill_enabled(skill_id, bool(payload.get("enabled", True)))


# ---------------------------------------------------------------- aiohttp 注册

def _send(data: Any, status: int = 200):
    from aiohttp import web

    return web.json_response(data, status=status, dumps=partial(json.dumps, ensure_ascii=False))


def _ok(data: Any):
    return _send(data)


def _error(message: str, status: int):
    return _send({"error": message}, status)


def register_routes() -> None:
    """把处理器挂到 ComfyUI PromptServer。仅在 ComfyUI 运行时可用。"""
    try:
        from server import PromptServer  # type: ignore
    except Exception as exc:  # noqa: BLE001
        logger.warning("AI Prompt Studio: 跳过路由注册（非 ComfyUI 环境）：%s", exc)
        return

    store = get_store()
    routes = PromptServer.instance.routes

    async def _run(request, func: Callable[..., Any]):
        payload: Dict[str, Any] = {}
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if request.body_exists:
                try:
                    payload = await request.json()
                except Exception as exc:  # noqa: BLE001
                    return _error(f"请求 JSON 无法解析：{exc.__class__.__name__}", 400)
                if not isinstance(payload, dict):
                    return _error("请求 JSON 必须是对象", 400)
        try:
            # 探测、运行时控制和档案持久化均可能执行同步 I/O；统一移出
            # aiohttp/ComfyUI 事件循环，避免设置页冻结数秒。
            result = await asyncio.to_thread(func, request, payload, store)
            return _ok(result)
        except KeyError as exc:
            return _error(str(exc), 404)
        except ValueError as exc:
            return _error(str(exc), 400)
        except Exception as exc:  # noqa: BLE001
            logger.exception("AI Prompt Studio 路由异常: %s", request.path)
            return _error(f"服务器内部错误：{exc.__class__.__name__}", 500)

    async def r_status(request):
        return await _run(request, lambda req, payload, st: handle_status(st))

    async def r_profiles_list(request):
        return await _run(request, lambda req, payload, st: handle_list_profiles(st))

    async def r_profiles_get(request):
        pid = request.match_info["profile_id"]
        return await _run(request, lambda req, payload, st: handle_get_profile(pid, st))

    async def r_profiles_create(request):
        return await _run(request, lambda req, payload, st: handle_create_profile(payload, st))

    async def r_profiles_update(request):
        pid = request.match_info["profile_id"]
        return await _run(request, lambda req, payload, st: handle_update_profile(pid, payload, st))

    async def r_profiles_delete(request):
        pid = request.match_info["profile_id"]
        return await _run(request, lambda req, payload, st: handle_delete_profile(pid, st))

    async def r_api_key_set(request):
        pid = request.match_info["profile_id"]
        return await _run(request, lambda req, payload, st: handle_set_api_key(pid, payload, st))

    async def r_api_key_clear(request):
        pid = request.match_info["profile_id"]
        return await _run(request, lambda req, payload, st: handle_clear_api_key(pid, st))

    async def r_probe(request):
        pid = request.match_info["profile_id"]
        return await _run(request, lambda req, payload, st: handle_probe(pid, st))

    async def r_test(request):
        pid = request.match_info["profile_id"]
        return await _run(request, lambda req, payload, st: handle_test(pid, st))

    async def r_capabilities(request):
        pid = request.query.get("profile_id") or None
        return await _run(request, lambda req, payload, st: handle_capabilities(pid, st))

    async def r_log(request):
        return await _run(request, lambda req, payload, st: handle_log(st))

    async def r_settings_get(request):
        return await _run(request, lambda req, payload, st: handle_settings_get(st))

    async def r_settings_set(request):
        return await _run(request, lambda req, payload, st: handle_settings_set(payload, st))

    async def r_runtime(request):
        return await _run(request, lambda req, payload, st: handle_runtime(payload, st))

    async def r_skills_list(request):
        return await _run(request, lambda req, payload, st: handle_skills_list(st))

    async def r_skill_get(request):
        sid = request.match_info["skill_id"]
        return await _run(request, lambda req, payload, st: handle_skill_get(sid, st))

    async def r_skill_create(request):
        return await _run(request, lambda req, payload, st: handle_skill_create(payload, st))

    async def r_skill_update(request):
        sid = request.match_info["skill_id"]
        return await _run(request, lambda req, payload, st: handle_skill_update(sid, payload, st))

    async def r_skill_delete(request):
        sid = request.match_info["skill_id"]
        return await _run(request, lambda req, payload, st: handle_skill_delete(sid, st))

    async def r_skill_enable(request):
        sid = request.match_info["skill_id"]
        return await _run(request, lambda req, payload, st: handle_skill_set_enabled(sid, payload, st))

    routes.get(f"{API_PREFIX}/status")(r_status)
    routes.get(f"{API_PREFIX}/profiles")(r_profiles_list)
    routes.get(f"{API_PREFIX}/profiles/{{profile_id}}")(r_profiles_get)
    routes.post(f"{API_PREFIX}/profiles")(r_profiles_create)
    routes.put(f"{API_PREFIX}/profiles/{{profile_id}}")(r_profiles_update)
    routes.delete(f"{API_PREFIX}/profiles/{{profile_id}}")(r_profiles_delete)
    routes.post(f"{API_PREFIX}/profiles/{{profile_id}}/api_key")(r_api_key_set)
    routes.delete(f"{API_PREFIX}/profiles/{{profile_id}}/api_key")(r_api_key_clear)
    routes.post(f"{API_PREFIX}/profiles/{{profile_id}}/probe")(r_probe)
    routes.post(f"{API_PREFIX}/profiles/{{profile_id}}/test")(r_test)
    routes.get(f"{API_PREFIX}/capabilities")(r_capabilities)
    routes.get(f"{API_PREFIX}/log")(r_log)
    routes.get(f"{API_PREFIX}/settings")(r_settings_get)
    routes.post(f"{API_PREFIX}/settings")(r_settings_set)
    routes.post(f"{API_PREFIX}/runtime")(r_runtime)
    routes.get(f"{API_PREFIX}/skills")(r_skills_list)
    routes.get(f"{API_PREFIX}/skills/{{skill_id}}")(r_skill_get)
    routes.post(f"{API_PREFIX}/skills")(r_skill_create)
    routes.put(f"{API_PREFIX}/skills/{{skill_id}}")(r_skill_update)
    routes.delete(f"{API_PREFIX}/skills/{{skill_id}}")(r_skill_delete)
    routes.post(f"{API_PREFIX}/skills/{{skill_id}}/enabled")(r_skill_enable)

    logger.info("AI Prompt Studio: 路由已注册（%s）", API_PREFIX)

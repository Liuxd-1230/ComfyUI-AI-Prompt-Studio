"""冒烟：真实 aiohttp 路由注册 + HTTP 往返（不依赖 ComfyUI/torch）。

register_routes() 把处理器挂到 PromptServer.instance.routes（web.RouteTableDef）。
本测试伪造 `server` 模块（PromptServer.instance.routes = RouteTableDef()），
用真实 aiohttp 起一个临时 HTTP 服务做端到端验证：状态、档案 CRUD、密钥隔离。
"""
import asyncio
import json
import sys
import tempfile
import types
from pathlib import Path

import pytest
from aiohttp import web

import aps.server.routes as aps_routes

EXPECTED_ROUTE_PATHS = {
    ("GET", "/ai_prompt_studio/status"),
    ("GET", "/ai_prompt_studio/profiles"),
    ("GET", "/ai_prompt_studio/profiles/{profile_id}"),
    ("POST", "/ai_prompt_studio/profiles"),
    ("PUT", "/ai_prompt_studio/profiles/{profile_id}"),
    ("DELETE", "/ai_prompt_studio/profiles/{profile_id}"),
    ("POST", "/ai_prompt_studio/profiles/{profile_id}/api_key"),
    ("DELETE", "/ai_prompt_studio/profiles/{profile_id}/api_key"),
    ("POST", "/ai_prompt_studio/profiles/{profile_id}/probe"),
    ("POST", "/ai_prompt_studio/profiles/{profile_id}/test"),
    ("GET", "/ai_prompt_studio/capabilities"),
    ("GET", "/ai_prompt_studio/log"),
    ("GET", "/ai_prompt_studio/settings"),
    ("POST", "/ai_prompt_studio/settings"),
    ("POST", "/ai_prompt_studio/runtime"),
    ("GET", "/ai_prompt_studio/skills"),
    ("GET", "/ai_prompt_studio/skills/{skill_id}"),
    ("POST", "/ai_prompt_studio/skills"),
    ("PUT", "/ai_prompt_studio/skills/{skill_id}"),
    ("DELETE", "/ai_prompt_studio/skills/{skill_id}"),
    ("POST", "/ai_prompt_studio/skills/{skill_id}/enabled"),
    ("GET", "/ai_prompt_studio/recovery/{session_id}/{node_instance_id}"),
    ("DELETE", "/ai_prompt_studio/recovery/{session_id}/{node_instance_id}"),
}


@pytest.fixture()
def table():
    """伪造 ComfyUI server 模块并返回注册用的 RouteTableDef。"""
    fake_server = types.ModuleType("server")
    table = web.RouteTableDef()
    pserver = types.SimpleNamespace(routes=table)
    fake_server.PromptServer = type("PromptServer", (), {"instance": pserver})
    sys.modules["server"] = fake_server
    yield table
    sys.modules.pop("server", None)


def test_register_registers_all_routes(table):
    aps_routes.register_routes()
    registered = {(r.method, r.path) for r in table._items}
    assert registered == EXPECTED_ROUTE_PATHS
    assert len(table._items) == len(EXPECTED_ROUTE_PATHS)


async def _http_roundtrip(table, store):
    app = web.Application()
    app.add_routes(table)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    base = f"http://127.0.0.1:{port}"

    import aiohttp
    from aps.services import skills as skills_svc

    # 自定义技能目录重定向到测试临时目录（避免污染真实用户配置）
    skills_svc.reset_cache()
    skills_svc.custom_skills_dir = lambda: store.base_dir / "skills"

    async with aiohttp.ClientSession() as client:
        # 状态
        async with client.get(f"{base}/ai_prompt_studio/status") as resp:
            assert resp.status == 200
            body = await resp.json()
            assert body["name"] == "AI Prompt Studio"
            assert body["profile_count"] == 0

        # 创建档案（含试图注入的密钥字段 → 必须被白名单剥离）
        async with client.post(
            f"{base}/ai_prompt_studio/profiles",
            json={"profile_id": "smoke1", "name": "冒烟档案",
                  "api_key": "sk-leak-me", "api_key_ref": "ref-leak-me"},
        ) as resp:
            assert resp.status == 200
            created = await resp.json()
            assert created["profile_id"] == "smoke1"
            raw = json.dumps(created)
            assert "sk-leak-me" not in raw and "ref-leak-me" not in raw

        # 落盘隔离
        persisted = json.loads((store.base_dir / "config.json").read_text(encoding="utf-8"))
        profile_raw = persisted["profiles"][0]
        assert "api_key" not in profile_raw and "api_key_ref" not in profile_raw

        # 列表
        async with client.get(f"{base}/ai_prompt_studio/profiles") as resp:
            assert resp.status == 200
            body = await resp.json()
            assert body["profiles"][0]["profile_id"] == "smoke1"

        # 缺省档案解析（空 profile_id 回退默认）
        from aps.server.config_store import get_store
        assert get_store().get_default_profile().profile_id == "smoke1"

        # 不存在的档案 → 404
        async with client.get(f"{base}/ai_prompt_studio/profiles/nope") as resp:
            assert resp.status == 404

        # 非法 payload → 400（非法 profile id）
        async with client.post(
            f"{base}/ai_prompt_studio/profiles",
            json={"profile_id": "../evil", "name": "x"},
        ) as resp:
            assert resp.status == 400

        # 设置读写
        async with client.post(
            f"{base}/ai_prompt_studio/settings", json={"settings": {"lang": "zh"}}
        ) as resp:
            assert resp.status == 200
        async with client.post(
            f"{base}/ai_prompt_studio/settings",
            data="{bad json", headers={"Content-Type": "application/json"},
        ) as resp:
            assert resp.status == 400
        async with client.get(f"{base}/ai_prompt_studio/settings") as resp:
            assert (await resp.json())["settings"]["lang"] == "zh"

        # Recovery Journal：浏览器只在磁盘 revision 更新时拿到候选快照。
        from aps.services.recovery import get_recovery_journal
        from aps.schemas.prompt_session import PromptSession
        recovery_session = PromptSession(
            target_family="anima", node_instance_id="node-42")
        recovery_session.commit(
            {"scene": "rain"}, "rain", {"valid": True, "issues": []},
            "create", "created", expected_revision=0,
            node_instance_id="node-42",
            recovery_journal=get_recovery_journal(store.base_dir))
        async with client.get(
            f"{base}/ai_prompt_studio/recovery/{recovery_session.id}/node-42"
        ) as resp:
            assert resp.status == 200
            recovery = await resp.json()
            assert recovery["found"] is True
            assert recovery["result_revision"] == 1
            assert recovery["session_snapshot"]["current_prompt"] == "rain"
        async with client.delete(
            f"{base}/ai_prompt_studio/recovery/{recovery_session.id}/node-42"
        ) as resp:
            assert resp.status == 200
        async with client.get(
            f"{base}/ai_prompt_studio/recovery/{recovery_session.id}/node-42"
        ) as resp:
            assert (await resp.json())["found"] is False

        # Prompt Skill：列表（内置只读）→ 复制为自定义 → 修改 → 停用 → 删除
        from aps.services import skills as skills_svc

        skills_svc.reset_cache()
        try:
            async with client.get(f"{base}/ai_prompt_studio/skills") as resp:
                assert resp.status == 200
                skills = (await resp.json())["skills"]
                assert any(s["id"] == "prompt_studio_anima" and s["source"] == "builtin"
                           for s in skills)

            async with client.post(
                f"{base}/ai_prompt_studio/skills",
                json={"copy_from": "prompt_studio_anima"},
            ) as resp:
                assert resp.status == 200
                rec = await resp.json()
                assert rec["id"] == "prompt_studio_anima" and rec["source"] == "custom"

            async with client.put(
                f"{base}/ai_prompt_studio/skills/prompt_studio_anima",
                json={"id": "prompt_studio_anima", "version": "9.9",
                      "target_family": "anima", "renderer": "anima_plan",
                      "system_prompt": "modified"},
            ) as resp:
                assert resp.status == 200
                assert (await resp.json())["version"] == "9.9"

            async with client.post(
                f"{base}/ai_prompt_studio/skills/prompt_studio_anima/enabled",
                json={"enabled": False},
            ) as resp:
                assert resp.status == 200
                assert (await resp.json())["enabled"] is False

            # 内置技能不允许删除 → 400（ValueError）
            async with client.delete(f"{base}/ai_prompt_studio/skills/nonexistent") as resp:
                assert resp.status == 404

            async with client.delete(
                f"{base}/ai_prompt_studio/skills/prompt_studio_anima") as resp:
                assert resp.status == 200

            async with client.get(
                f"{base}/ai_prompt_studio/skills/nope") as resp:
                assert resp.status == 404
        finally:
            skills_svc.reset_cache()

    await runner.cleanup()


def test_http_roundtrip(table, store):
    aps_routes.register_routes()
    asyncio.run(_http_roundtrip(table, store))

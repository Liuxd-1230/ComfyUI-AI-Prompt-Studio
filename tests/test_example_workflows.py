"""示例工作流 JSON 验证：可加载（节点类型已注册）、连线一致、不含密钥。"""
import json
from pathlib import Path

import pytest

import aps

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

# 核心节点类型（非本扩展），跳过注册检查
CORE_TYPES = {"Note", "Reroute", "PrimitiveNode"}


@pytest.mark.parametrize("name", ["h3_full_chain.json", "anima_full_chain.json"])
def test_workflow_loadable_and_registered(name):
    path = EXAMPLES / name
    data = json.loads(path.read_text(encoding="utf-8"))
    nodes = {n["id"]: n for n in data["nodes"]}
    assert len(nodes) >= 2
    for n in data["nodes"]:
        if n["type"] in CORE_TYPES:
            continue
        assert n["type"] in aps.NODE_CLASS_MAPPINGS, \
            f"{name}: 节点类型 {n['type']} 未注册"


@pytest.mark.parametrize("name", ["h3_full_chain.json", "anima_full_chain.json"])
def test_workflow_links_consistent(name):
    data = json.loads((EXAMPLES / name).read_text(encoding="utf-8"))
    nodes = {n["id"]: n for n in data["nodes"]}
    seen = set()
    for link in data.get("links", []):
        link_id, src_id, src_slot, dst_id, dst_slot, typ = link
        assert link_id not in seen
        seen.add(link_id)
        src, dst = nodes[src_id], nodes[dst_id]
        assert src_slot < len(src["outputs"]), f"{name}: link{link_id} 源槽越界"
        assert dst_slot < len(dst["inputs"]), f"{name}: link{link_id} 目标槽越界"
        assert src["outputs"][src_slot]["type"] == typ
        assert dst["inputs"][dst_slot]["type"] == typ
        # 输入连线在 inputs 里登记
        assert dst["inputs"][dst_slot]["link"] == link_id
        # 输出连线登记
        assert link_id in (src["outputs"][src_slot]["links"] or [])


@pytest.mark.parametrize("name", ["h3_full_chain.json", "anima_full_chain.json"])
def test_workflow_contains_no_secrets(name):
    text = (EXAMPLES / name).read_text(encoding="utf-8").lower()
    for bad in ("api_key", "sk-", "apikey", "token:", "secret"):
        assert bad not in text, f"{name}: 工作流 JSON 不应包含 {bad!r}"
    # AI_PROFILE 节点 widgets 不含 api_key_ref
    data = json.loads(text)
    for n in data["nodes"]:
        assert "api_key_ref" not in json.dumps(n), f"{name}: 节点 {n['id']} 含 api_key_ref"


def test_examples_directory_has_both_chains():
    files = {p.name for p in EXAMPLES.glob("*.json")}
    assert {"h3_full_chain.json", "anima_full_chain.json"} <= files

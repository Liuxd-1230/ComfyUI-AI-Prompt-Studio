"""搜索策略（services/search.py）测试：降级链决议。"""
from aps.schemas.profile import AIProfile
from aps.services import search


def test_policy_off_disables():
    s = search.resolve_search_strategy(AIProfile(), {}, "off")
    assert s["enabled"] is False


def test_native_available():
    s = search.resolve_search_strategy(AIProfile(), {"native_web_search": True}, "always")
    assert s["enabled"] is True and s["native"] is True and s["warning"] == ""


def test_native_unknown_tries_with_warning():
    s = search.resolve_search_strategy(AIProfile(), {"native_web_search": "unknown"}, "always")
    assert s["enabled"] is True and s["native"] is True
    assert "未探测" in s["warning"]


def test_native_unavailable_offline_degrade():
    s = search.resolve_search_strategy(AIProfile(), {"native_web_search": False}, "auto")
    assert s["enabled"] is True and s["native"] is False
    assert "不支持原生联网搜索" in s["warning"]


def test_offline_result_message():
    r = search.offline_result("p1", "今天天气")
    assert "今天天气" in r["warning"]


def test_search_backend_slot_not_implemented():
    b = search.SearchBackend()
    try:
        b.search("x")
        assert False, "外部后端未实现应抛 NotImplementedError"
    except NotImplementedError:
        pass

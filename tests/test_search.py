"""搜索策略（services/search.py）测试：降级链决议。"""
from aps.schemas.profile import AIProfile
from aps.services import search


def test_policy_off_disables():
    s = search.resolve_search_strategy(AIProfile(), {}, "off")
    assert s["enabled"] is False


def test_native_available():
    s = search.resolve_search_strategy(AIProfile(), {"native_web_search": True}, "always")
    assert s["enabled"] is True and s["native"] is True and s["warning"] == ""


def test_auto_only_offers_the_native_tool():
    s = search.resolve_search_strategy(AIProfile(), {"native_web_search": True}, "auto")
    assert (s["enabled"], s["native"], s["forced"]) == (True, True, False)


def test_always_forces_the_native_tool():
    s = search.resolve_search_strategy(AIProfile(), {"native_web_search": True}, "always")
    assert (s["enabled"], s["native"], s["forced"]) == (True, True, True)


def test_unprobed_capability_is_treated_as_unsupported():
    """未探测（缺键或 None）与实测 False 同口径：不猜原生联网可用。"""
    for caps in ({}, {"native_web_search": False}, {"native_web_search": None}):
        s = search.resolve_search_strategy(AIProfile(), caps, "always")
        assert (s["enabled"], s["native"]) == (False, False), caps


def test_auto_without_any_backend_is_silent():
    """auto 是档案默认值：没有联网能力时静默不搜，不给每次请求加警告噪声。"""
    s = search.resolve_search_strategy(AIProfile(), {"native_web_search": False}, "auto")
    assert s["enabled"] is False and s["warning"] == ""


def test_always_without_any_backend_warns():
    s = search.resolve_search_strategy(AIProfile(), {"native_web_search": False}, "always")
    assert s["enabled"] is False and "always" in s["warning"]


def test_external_backend_serves_both_auto_and_always():
    profile = AIProfile(search_url="https://s.example/search")
    for policy in ("auto", "always"):
        s = search.resolve_search_strategy(profile, {}, policy)
        assert (s["enabled"], s["native"], s["reason"]) == (True, False, "external"), policy


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

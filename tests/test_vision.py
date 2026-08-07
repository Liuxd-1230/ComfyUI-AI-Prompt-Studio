"""视觉服务测试：图片编码 / 多模态消息 / 端点调用（mock requests）。"""
import io

import numpy as np
import pytest
import requests
from PIL import Image

from aps.schemas.profile import AIProfile
from aps.services import vision
from aps.services.vision import VisionUnavailable


def test_image_to_data_url_from_pil():
    img = Image.new("RGB", (64, 48), (200, 30, 30))
    url = vision.image_to_data_url(img)
    assert url.startswith("data:image/png;base64,")
    assert len(url) > 100


def test_image_to_data_url_from_numpy_float():
    arr = np.random.rand(32, 32, 3).astype(np.float32)
    url = vision.image_to_data_url(arr)
    assert url.startswith("data:image/png;base64,")


def test_image_to_data_url_from_numpy_uint8_rgba():
    arr = np.zeros((20, 20, 4), dtype=np.uint8)
    arr[..., 3] = 255  # 不透明
    url = vision.image_to_data_url(arr)
    assert url.startswith("data:image/png;base64,")


def test_image_to_data_url_max_side_resize():
    img = Image.new("RGB", (2048, 100), (10, 10, 10))
    url = vision.image_to_data_url(img, max_side=1024)
    # 重新解码验证尺寸
    import base64

    b64 = url.split(",", 1)[1]
    decoded = Image.open(io.BytesIO(base64.b64decode(b64)))
    assert max(decoded.size) <= 1024


def test_build_vision_messages():
    msgs = vision.build_vision_messages("describe", ["data:image/png;base64,AAA"])
    content = msgs[0]["content"]
    assert content[0] == {"type": "text", "text": "describe"}
    assert content[1] == {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}}


def test_require_vision_raises_without_config():
    with pytest.raises(VisionUnavailable, match="vision_base_url"):
        vision.require_vision(AIProfile(profile_id="p1"))


def test_call_vision_ok(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        assert "chat/completions" in url
        assert json["model"] == "qwen-vl-max"
        return FakeResp(200, {"choices": [{"message": {"content": "红发少女"}}]})

    monkeypatch.setattr(requests, "post", fake_post)
    profile = AIProfile(profile_id="p1", vision_base_url="http://v:8000/v1",
                        vision_model="qwen-vl-max")
    res = vision.call_vision(profile, "k", vision.build_vision_messages("x", ["u"]))
    assert res["ok"] is True and res["text"] == "红发少女"


def test_call_vision_auth_error(monkeypatch):
    monkeypatch.setattr(requests, "post",
                        lambda *a, **k: FakeResp(401, {}))
    profile = AIProfile(profile_id="p1", vision_base_url="http://v",
                        vision_model="m")
    res = vision.call_vision(profile, "bad", [])
    assert res["ok"] is False
    assert res["error"].kind == "auth_error"


def test_call_vision_network_error(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(requests, "post", boom)
    profile = AIProfile(profile_id="p1", vision_base_url="http://v", vision_model="m")
    res = vision.call_vision(profile, "k", [])
    assert res["error"].kind == "network_error"


class FakeResp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload or {}

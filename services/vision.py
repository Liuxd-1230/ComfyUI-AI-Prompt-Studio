"""视觉服务：图片编码为 base64 data URL，调用视觉端点做多模态分析。

决策（docs/decisions.md D8）：视觉 = 档案配置的通用 OpenAI 兼容端点
（vision_model + 可选 vision_base_url）；视觉地址留空时复用档案 base_url。
本模块不依赖 torch（节点层负责把 ComfyUI 张量转 numpy）。
"""
from __future__ import annotations

import base64
import io
import logging
from typing import Any, Dict, List, Optional

import requests

from ..schemas.profile import AIProfile
from ..schemas.results import make_error
from .adapters.base import is_protocol_unsupported, map_http_error

logger = logging.getLogger("ai_prompt_studio.vision")

MAX_IMAGE_SIDE = 1024  # 长边缩放上限（控制 token/延迟）


class VisionUnavailable(Exception):
    """未配置视觉模型。"""


def image_to_data_url(image, max_side: int = MAX_IMAGE_SIDE) -> str:
    """PIL.Image / numpy 数组 → PNG base64 data URL。

    numpy 输入：接受 (H,W,3|4) float 0-1 或 int 0-255；自动转 RGB。
    """
    from PIL import Image
    import numpy as np

    if isinstance(image, np.ndarray):
        arr = image
        if arr.dtype.kind == "f":
            arr = np.clip(arr, 0.0, 1.0)
            arr = (arr * 255.0 + 0.5).astype(np.uint8)
        else:
            arr = np.asarray(arr, dtype=np.uint8)
        if arr.ndim == 3 and arr.shape[-1] in (3, 4):
            img = Image.fromarray(arr, mode="RGB" if arr.shape[-1] == 3 else "RGBA")
        elif arr.ndim == 2:
            img = Image.fromarray(arr, mode="L")
        else:
            raise ValueError(f"无法识别的图像数组形状: {arr.shape}")
    elif isinstance(image, Image.Image):
        img = image
    else:
        raise TypeError(f"不支持的图像类型: {type(image).__name__}")

    if img.mode in ("RGBA", "P", "LA"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        try:
            bg.paste(img, mask=img.split()[-1])
        except ValueError:
            bg.paste(img.convert("RGB"))
        img = bg
    else:
        img = img.convert("RGB")

    if max_side and max(img.size) > max_side:
        ratio = max_side / float(max(img.size))
        img = img.resize((max(1, int(img.width * ratio)),
                          max(1, int(img.height * ratio))), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def build_vision_messages(prompt: str, data_urls: List[str]) -> List[Dict[str, Any]]:
    """构造多模态 user 消息（文本 + 图片 content parts）。"""
    content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
    for url in data_urls:
        content.append({"type": "image_url",
                        "image_url": {"url": url}})
    return [{"role": "user", "content": content}]


def require_vision(profile: AIProfile) -> str:
    """校验视觉配置，返回 base_url。未配置抛 VisionUnavailable。"""
    base = (profile.vision_base_url or profile.base_url or "").rstrip("/")
    if not profile.vision_model:
        raise VisionUnavailable(
            "档案未配置视觉模型：请在 AI Prompt Studio 设置面板为该档案填写 "
            "vision_model；vision_base_url 留空时复用主 API URL。"
        )
    return base


def resolve_vision_profile(profile: AIProfile) -> AIProfile:
    """视觉/文本 Profile 解耦：返回实际用于视觉分析的档案。

    profile.vision_profile_id 非空 → 视觉使用该档案（其 vision_* 配置与 api_key）；
    留空 → 使用本档案自身的 vision_* 配置。
    仅做字段回填，不改动原档案；返回 None 表示需要外部解析（未找到目标档案时
    由调用方报错，避免本模块依赖 ConfigStore 造成循环导入）。
    """
    if not (profile.vision_profile_id or "").strip():
        return profile
    # 延迟导入避免循环依赖
    try:
        from ..server.config_store import get_store
        store = get_store()
    except Exception:  # noqa: BLE001
        return profile
    target = store.get_profile(profile.vision_profile_id.strip())
    if target is None:
        raise VisionUnavailable(
            f"vision_profile_id={profile.vision_profile_id!r} 指向的档案不存在，"
            "请在设置面板检查")
    return linked_vision_profile(target)


def linked_vision_profile(target: AIProfile) -> AIProfile:
    """把关联档案规范成视觉调用配置。

    关联档案本身就是一个完整服务档案，因此默认直接使用它的主 endpoint/model/key；
    若它显式配置了 vision_*，则显式配置优先。这样 vision_profile_id 不再要求用户
    在目标档案中重复填写一遍相同模型。
    """
    resolved = AIProfile.from_json(target.to_json())
    resolved.vision_base_url = target.vision_base_url or target.base_url
    resolved.vision_model = target.vision_model or target.model
    resolved.vision_profile_id = ""
    return resolved


def call_vision(profile: AIProfile, api_key: str, messages: List[Dict[str, Any]],
                *, timeout: float = 120.0) -> Dict[str, Any]:
    """调用视觉端点，返回 {ok, text, error}。

    复用 Chat Completions 的请求形态（{vision_base_url}/chat/completions），
    错误归一化与 adapter 一致（401/429/5xx 硬失败，绝不伪装）。
    """
    base = require_vision(profile)
    url = f"{base}/chat/completions"
    body = {
        "model": profile.vision_model,
        "messages": messages,
        "stream": False,
        "max_tokens": 2048,
    }
    headers = {"Authorization": f"Bearer {api_key}",
               "Content-Type": "application/json"}
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=(10.0, timeout))
    except requests.Timeout:
        return {"ok": False, "error": make_error("timeout", "视觉请求超时")}
    except requests.RequestException as exc:
        return {"ok": False,
                "error": make_error("network_error",
                                    f"无法连接视觉端点 {url}：{exc.__class__.__name__}")}

    if resp.status_code != 200:
        body_text = _safe_body(resp)
        if is_protocol_unsupported(resp.status_code, body_text):
            return {"ok": False,
                    "error": make_error("protocol_unsupported",
                                        f"视觉端点不支持（HTTP {resp.status_code}）：{body_text[:150]}")}
        return {"ok": False, "error": map_http_error(resp.status_code, body_text[:200])}

    try:
        payload = resp.json()
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": make_error("server_error", "视觉端点返回非 JSON 响应")}

    text = ""
    try:
        text = payload["choices"][0]["message"]["content"] or ""
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": make_error("server_error", "视觉端点响应结构异常")}
    return {"ok": True, "text": text, "raw": _safe_body(resp)}


def _safe_body(resp) -> str:
    try:
        return resp.text[:2000]
    except Exception:  # noqa: BLE001
        return ""

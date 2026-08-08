"""档案能力主动探测。

手动点击“重新探测”时，以运行时实际使用的请求格式调用模型端点。模型目录只
用于填充下拉框，不再推断推理、结构化输出、工具、视觉或文件能力。
"""
from __future__ import annotations

import base64
import json
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from ..schemas.profile import AIProfile
from .vision import linked_vision_profile

DEFAULT_TIMEOUT = 15.0
PROBE_OUTPUT_TOKENS = 32
STRUCTURED_OUTPUT_TOKENS = 64
_MAGENTA_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAFElEQVR4nGP8z/CfARtgwio6aCUAkYsCDoRKzmMAAAAASUVORK5CYII="
)
_FILE_SENTINEL = "APS_FILE_7D3C"
_FILE_DATA = base64.b64encode(_FILE_SENTINEL.encode("utf-8")).decode("ascii")
_SCHEMA = {
    "type": "object",
    "properties": {"aps_probe": {"type": "string", "enum": ["ok"]}},
    "required": ["aps_probe"],
    "additionalProperties": False,
}

# 未探测时只用于 auto 协议的安全默认值。当前 DeepSeek 官方公开接口为
# Chat Completions；实际能力仍以主动探测结果为准。
DEEPSEEK_MODEL_CAPS = {
    "deepseek-v4-flash": {"responses": False, "chat_completions": True},
    "deepseek-v4-pro": {"responses": False, "chat_completions": True},
}


def _catalog_entries(payload: Any) -> List[Dict[str, Any]]:
    raw = payload if isinstance(payload, list) else (
        payload.get("data") or payload.get("models") or []
        if isinstance(payload, dict) else [])
    return [item for item in raw if isinstance(item, dict)]


def _model_id(entry: Dict[str, Any]) -> str:
    return str(entry.get("id") or entry.get("key") or entry.get("name") or "").strip()


def _match_deepseek_model(model: str, models=None) -> Optional[str]:
    candidate = (model or "").strip()
    for key in DEEPSEEK_MODEL_CAPS:
        if candidate == key or key in candidate or candidate in key:
            return key
    return None


def deepseek_known_responses(model: str) -> Optional[bool]:
    key = _match_deepseek_model(model)
    return None if key is None else bool(DEEPSEEK_MODEL_CAPS[key]["responses"])


def _is_official_deepseek_base(base_url: str) -> bool:
    base = (base_url or "https://api.deepseek.com").strip()
    return (urlparse(base).hostname or "").lower() == "api.deepseek.com"


def supports_native_structured_output(profile: AIProfile, caps: dict,
                                     protocol: str) -> bool:
    key = "structured_output_responses" if protocol == "responses" \
        else "structured_output_chat"
    return bool(caps and caps.get(key) is True)


def _status_kind(status: int) -> str:
    if status == 401:
        return "auth_error"
    if status == 402:
        return "insufficient_balance"
    if status == 403:
        return "forbidden"
    if status == 429:
        return "rate_limit"
    if 400 <= status < 500:
        return "invalid_request"
    if status >= 500:
        return "server_error"
    return "network_error" if not status else "unknown"


def _body_text(response: Any) -> str:
    try:
        return str(response.text or "")[:500]
    except Exception:  # noqa: BLE001
        return ""


def _request_json(method: str, url: str, headers: Dict[str, str], *,
                  timeout: float, body: Optional[Dict[str, Any]] = None
                  ) -> Tuple[int, Dict[str, Any], str]:
    try:
        if method == "GET":
            response = requests.get(url, headers=headers, timeout=timeout)
        else:
            response = requests.post(url, headers=headers, json=body, timeout=timeout)
    except requests.RequestException as exc:
        return 0, {}, f"{exc.__class__.__name__}: {exc}"
    try:
        payload = response.json()
        if not isinstance(payload, dict):
            payload = {"data": payload}
    except Exception:  # noqa: BLE001
        payload = {}
    detail = "" if response.status_code == 200 else (
        _error_message(payload) or _body_text(response) or f"HTTP {response.status_code}")
    return response.status_code, payload, detail


def _error_message(payload: Dict[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or "")
    return str(error or "")


def _chat_text(payload: Dict[str, Any]) -> str:
    try:
        content = payload["choices"][0]["message"].get("content")
    except (KeyError, IndexError, TypeError, AttributeError):
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "".join(str(part.get("text", "")) for part in content
                       if isinstance(part, dict)).strip()
    return ""


def _responses_text(payload: Dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"].strip()
    parts: List[str] = []
    for item in payload.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                parts.append(content["text"])
    return "".join(parts).strip()


def _check(status: int, endpoint: str, ok: bool, detail: str = "") -> Dict[str, Any]:
    if not detail:
        detail = "通过真实请求验证" if ok else (
            f"HTTP {status}" if status else "网络请求失败")
    return {"ok": bool(ok), "endpoint": endpoint, "http_status": status,
            "detail": detail[:300]}


def _post_probe(endpoint: str, headers: Dict[str, str], body: Dict[str, Any],
                timeout: float, parser) -> Tuple[int, Dict[str, Any], str, str]:
    status, payload, detail = _request_json(
        "POST", endpoint, headers, timeout=timeout, body=body)
    text = parser(payload) if status == 200 else ""
    if status == 200 and not text:
        detail = _error_message(payload) or "HTTP 200，但响应中没有可用的模型文本"
    return status, payload, detail, text


def _chat_body(model: str, prompt: str, *, max_tokens: int = PROBE_OUTPUT_TOKENS,
               content: Any = None) -> Dict[str, Any]:
    return {"model": model, "messages": [{"role": "user", "content": content or prompt}],
            "stream": False, "max_tokens": max_tokens}


def _responses_body(model: str, prompt: str, *,
                    max_tokens: int = PROBE_OUTPUT_TOKENS,
                    content: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    input_value: Any = prompt
    if content is not None:
        input_value = [{"role": "user", "content": content}]
    return {"model": model, "input": input_value, "stream": False,
            "max_output_tokens": max_tokens}


def _tool_call_chat(payload: Dict[str, Any]) -> bool:
    try:
        calls = payload["choices"][0]["message"].get("tool_calls") or []
    except (KeyError, IndexError, TypeError, AttributeError):
        return False
    return any(call.get("function", {}).get("name") == "aps_probe_tool"
               for call in calls if isinstance(call, dict))


def _tool_call_responses(payload: Dict[str, Any]) -> bool:
    return any(item.get("type") == "function_call" and
               item.get("name") == "aps_probe_tool"
               for item in payload.get("output", []) if isinstance(item, dict))


def _web_call(payload: Dict[str, Any]) -> bool:
    return any(str(item.get("type", "")).startswith("web_search")
               for item in payload.get("output", []) if isinstance(item, dict))


def _valid_probe_json(text: str) -> bool:
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return False
    return isinstance(value, dict) and value == {"aps_probe": "ok"}


def _probe_protocols(profile: AIProfile, headers: Dict[str, str], timeout: float,
                     caps: Dict[str, Any], exhaustive: bool = True) -> None:
    base = profile.base_url.rstrip("/")
    chat_url = f"{base}/chat/completions"
    responses_url = f"{base}/responses"
    checks = caps["checks"]

    status, payload, detail, text = _post_probe(
        chat_url, headers, _chat_body(profile.model, "Reply APS_OK only."), timeout, _chat_text)
    caps["chat_completions"] = status == 200 and bool(text)
    checks["chat_completions"] = _check(status, chat_url, caps["chat_completions"], detail)

    status, payload, detail, text = _post_probe(
        responses_url, headers, _responses_body(profile.model, "Reply APS_OK only."),
        timeout, _responses_text)
    caps["responses"] = status == 200 and bool(text)
    checks["responses"] = _check(status, responses_url, caps["responses"], detail)

    if not exhaustive:
        return

    if caps["chat_completions"]:
        body = _chat_body(profile.model,
                          'Return JSON exactly as {"aps_probe":"ok"}.',
                          max_tokens=STRUCTURED_OUTPUT_TOKENS)
        body["response_format"] = {"type": "json_schema", "json_schema": {
            "name": "aps_probe", "schema": _SCHEMA, "strict": True}}
        status, payload, detail, text = _post_probe(
            chat_url, headers, body, timeout, _chat_text)
        ok = status == 200 and _valid_probe_json(text)
        caps["structured_output_chat"] = ok
        checks["structured_output_chat"] = _check(
            status, chat_url, ok, detail or ("Schema 被忽略" if status == 200 and not ok else ""))

        json_body = _chat_body(profile.model,
                               'Return JSON exactly as {"aps_probe":"ok"}.',
                               max_tokens=STRUCTURED_OUTPUT_TOKENS)
        json_body["response_format"] = {"type": "json_object"}
        status, payload, detail, text = _post_probe(
            chat_url, headers, json_body, timeout, _chat_text)
        ok = status == 200 and _valid_probe_json(text)
        caps["json_output_chat"] = ok
        checks["json_output_chat"] = _check(status, chat_url, ok, detail)

        tool = {"type": "function", "function": {
            "name": "aps_probe_tool", "description": "Capability probe",
            "parameters": {"type": "object", "properties": {},
                           "required": [], "additionalProperties": False}}}
        tool_body = _chat_body(profile.model, "Call aps_probe_tool now.")
        tool_body.update(tools=[tool], tool_choice={
            "type": "function", "function": {"name": "aps_probe_tool"}})
        status, payload, detail = _request_json(
            "POST", chat_url, headers, timeout=timeout, body=tool_body)
        ok = status == 200 and _tool_call_chat(payload)
        caps["function_tools_chat"] = ok
        checks["function_tools_chat"] = _check(status, chat_url, ok, detail)

        image_content = [
            {"type": "text", "text": "Name the single pixel's basic color, one uppercase word."},
            {"type": "image_url", "image_url": {"url": _MAGENTA_PNG, "detail": "low"}},
        ]
        status, payload, detail, text = _post_probe(
            chat_url, headers, _chat_body(profile.model, "", content=image_content),
            timeout, _chat_text)
        ok = status == 200 and any(word in text.upper() for word in ("MAGENTA", "PURPLE"))
        caps["vision_chat"] = ok
        checks["vision_chat"] = _check(status, chat_url, ok, detail)

        file_content = [
            {"type": "text", "text": "Read the attached file and reply with its exact content."},
            {"type": "file", "file": {"file_data": _FILE_DATA,
                                       "filename": "aps_probe.txt"}},
        ]
        status, payload, detail, text = _post_probe(
            chat_url, headers, _chat_body(profile.model, "", content=file_content),
            timeout, _chat_text)
        ok = status == 200 and _FILE_SENTINEL in text
        caps["files_chat"] = ok
        checks["files_chat"] = _check(status, chat_url, ok, detail)

    if caps["responses"]:
        body = _responses_body(profile.model,
                               'Return JSON exactly as {"aps_probe":"ok"}.',
                               max_tokens=STRUCTURED_OUTPUT_TOKENS)
        body["text"] = {"format": {"type": "json_schema", "name": "aps_probe",
                                   "schema": _SCHEMA, "strict": True}}
        status, payload, detail, text = _post_probe(
            responses_url, headers, body, timeout, _responses_text)
        ok = status == 200 and _valid_probe_json(text)
        caps["structured_output_responses"] = ok
        checks["structured_output_responses"] = _check(status, responses_url, ok, detail)

        tool = {"type": "function", "name": "aps_probe_tool",
                "description": "Capability probe",
                "parameters": {"type": "object", "properties": {},
                               "required": [], "additionalProperties": False}}
        tool_body = _responses_body(profile.model, "Call aps_probe_tool now.")
        tool_body.update(tools=[tool], tool_choice="required")
        status, payload, detail = _request_json(
            "POST", responses_url, headers, timeout=timeout, body=tool_body)
        ok = status == 200 and _tool_call_responses(payload)
        caps["function_tools_responses"] = ok
        checks["function_tools_responses"] = _check(status, responses_url, ok, detail)

        image_content = [
            {"type": "input_text", "text": "Name the single pixel's basic color, one uppercase word."},
            {"type": "input_image", "image_url": _MAGENTA_PNG, "detail": "low"},
        ]
        status, payload, detail, text = _post_probe(
            responses_url, headers,
            _responses_body(profile.model, "", content=image_content), timeout, _responses_text)
        ok = status == 200 and any(word in text.upper() for word in ("MAGENTA", "PURPLE"))
        caps["vision_responses"] = ok
        checks["vision_responses"] = _check(status, responses_url, ok, detail)

        file_content = [
            {"type": "input_text", "text": "Read the attached file and reply with its exact content."},
            {"type": "input_file", "file_data": _FILE_DATA,
             "filename": "aps_probe.txt"},
        ]
        status, payload, detail, text = _post_probe(
            responses_url, headers,
            _responses_body(profile.model, "", content=file_content), timeout, _responses_text)
        ok = status == 200 and _FILE_SENTINEL in text
        caps["files_responses"] = ok
        checks["files_responses"] = _check(status, responses_url, ok, detail)

        web_body = _responses_body(profile.model,
                                   "Use web search, then reply with one short fact.")
        web_body["tools"] = [{"type": "web_search"}]
        status, payload, detail = _request_json(
            "POST", responses_url, headers, timeout=timeout, body=web_body)
        ok = status == 200 and _web_call(payload)
        caps["native_web_search"] = ok
        checks["native_web_search"] = _check(status, responses_url, ok, detail)


def _probe_vision_service(profile: AIProfile, headers: Dict[str, str], timeout: float,
                          caps: Dict[str, Any]) -> None:
    if not profile.vision_model:
        caps["vision_service"] = False
        caps["vision_model_available"] = False
        return
    base = (profile.vision_base_url or profile.base_url).rstrip("/")
    endpoint = f"{base}/chat/completions"
    content = [
        {"type": "text", "text": "Name the single pixel's basic color, one uppercase word."},
        {"type": "image_url", "image_url": {"url": _MAGENTA_PNG, "detail": "low"}},
    ]
    status, payload, detail, text = _post_probe(
        endpoint, headers, _chat_body(profile.vision_model, "", content=content),
        timeout, _chat_text)
    ok = status == 200 and any(word in text.upper() for word in ("MAGENTA", "PURPLE"))
    if ok:
        detail = "已发送 8×8 洋红测试图，模型正确识别为 MAGENTA/PURPLE"
    elif status == 200 and text:
        detail = "模型返回了文本，但未正确识别 8×8 洋红测试图"
    caps["vision_service"] = ok
    caps["vision_model_available"] = ok or profile.vision_model in caps["vision_models"]
    caps["checks"]["vision_service"] = _check(status, endpoint, ok, detail)


def probe_profile(profile: AIProfile, api_key: str,
                  timeout: float = DEFAULT_TIMEOUT, *,
                  exhaustive: bool = True,
                  vision_profile: Optional[AIProfile] = None,
                  vision_api_key: str = "") -> Dict[str, Any]:
    """主动探测档案；有密钥时所有运行能力均返回明确 bool。"""
    boolean_fields = (
        "responses", "chat_completions", "function_tools",
        "function_tools_chat", "function_tools_responses", "native_web_search",
        "structured_output_responses", "structured_output_chat", "structured_output",
        "json_output_chat", "vision", "vision_chat", "vision_responses",
        "vision_service", "files", "files_chat", "files_responses",
    )
    caps: Dict[str, Any] = {field: False for field in boolean_fields}
    effective_vision = linked_vision_profile(vision_profile) if vision_profile else profile
    caps.update({
        "vision_configured": bool(effective_vision.vision_model),
        "vision_models": [], "vision_model_available": False,
        "model_listing": False, "models": [], "auth_ok": False,
        "error": None, "http_status": 0, "checks": {},
        "capability_basis": "active_execution_probe",
        "probed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    if not api_key:
        caps["error"] = "未配置 API Key，无法探测"
        return caps
    base = (profile.base_url or "").rstrip("/")
    if not base:
        caps["error"] = "base_url 为空"
        return caps
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    status, payload, detail = _request_json(
        "GET", f"{base}/models", headers, timeout=timeout)
    caps["http_status"] = status
    entries = _catalog_entries(payload) if status == 200 else []
    caps["models"] = [value for item in entries if (value := _model_id(item))]
    caps["model_listing"] = status == 200
    caps["checks"]["model_listing"] = _check(
        status, f"{base}/models", status == 200, detail)

    _probe_protocols(profile, headers, timeout, caps, exhaustive=exhaustive)

    # LM Studio 等本地 OpenAI 兼容服务的管理 API 位于根路径，但推理 API 位于
    # /v1。用户很容易把 http://127.0.0.1:1234 当成推理根地址；部分版本还会
    # 对错误端点返回 HTTP 200 + {error: ...}。仅在原地址两种协议都失败时实测
    # /v1，成功才采用，避免按端口或 provider 猜测。
    base_path = (urlparse(base).path or "").rstrip("/")
    if (not caps["chat_completions"] and not caps["responses"] and
            not base_path.endswith("/v1")):
        candidate_base = f"{base}/v1"
        candidate = AIProfile.from_json(profile.to_json())
        candidate.base_url = candidate_base
        candidate_caps: Dict[str, Any] = {field: False for field in boolean_fields}
        candidate_caps["checks"] = {}
        _probe_protocols(candidate, headers, timeout, candidate_caps,
                         exhaustive=exhaustive)
        if candidate_caps["chat_completions"] or candidate_caps["responses"]:
            v1_status, v1_payload, v1_detail = _request_json(
                "GET", f"{candidate_base}/models", headers, timeout=timeout)
            v1_entries = _catalog_entries(v1_payload) if v1_status == 200 else []
            caps.update(candidate_caps)
            caps["http_status"] = v1_status
            caps["models"] = [value for item in v1_entries
                              if (value := _model_id(item))]
            caps["model_listing"] = v1_status == 200
            caps["checks"]["model_listing"] = _check(
                v1_status, f"{candidate_base}/models",
                v1_status == 200, v1_detail)
            caps["checks"]["base_url_discovery"] = {
                "ok": True, "endpoint": candidate_base, "http_status": 200,
                "detail": f"原地址不是推理 API；已实测并采用 {candidate_base}",
            }
            caps["resolved_base_url"] = candidate_base
            caps["base_url_autocorrected"] = True
            profile = candidate
            base = candidate_base
            if vision_profile is None:
                effective_vision = profile

    vision_base = (effective_vision.vision_base_url or effective_vision.base_url).rstrip("/")
    vision_headers = headers if effective_vision is profile else {
        "Authorization": f"Bearer {vision_api_key}", "Content-Type": "application/json"}
    if effective_vision.vision_model:
        if vision_base == base:
            caps["vision_models"] = list(caps["models"])
        else:
            v_status, v_payload, v_detail = _request_json(
                "GET", f"{vision_base}/models", vision_headers, timeout=timeout)
            v_entries = _catalog_entries(v_payload) if v_status == 200 else []
            caps["vision_models"] = [value for item in v_entries if (value := _model_id(item))]
            caps["checks"]["vision_model_listing"] = _check(
                v_status, f"{vision_base}/models", v_status == 200, v_detail)
    if exhaustive:
        _probe_vision_service(effective_vision, vision_headers, timeout, caps)

    caps["function_tools"] = bool(
        caps["function_tools_chat"] or caps["function_tools_responses"])
    caps["structured_output"] = bool(
        caps["structured_output_chat"] or caps["structured_output_responses"])
    caps["vision"] = bool(caps["vision_chat"] or caps["vision_responses"])
    caps["files"] = bool(caps["files_chat"] or caps["files_responses"])
    caps["auth_ok"] = bool(caps["chat_completions"] or caps["responses"])
    if not caps["auth_ok"]:
        failures = [caps["checks"].get(name, {}).get("detail", "")
                    for name in ("chat_completions", "responses")]
        caps["error"] = "Chat 与 Responses 实测均失败：" + "；".join(
            value for value in failures if value)
        statuses = [caps["checks"].get(name, {}).get("http_status", 0)
                    for name in ("chat_completions", "responses")]
        decisive = next((value for value in statuses if value in (401, 402, 403, 429)),
                        next((value for value in statuses if value), 0))
        caps["error_kind"] = _status_kind(decisive)
    return caps


def merge_capabilities(existing: Dict[str, Any], fresh: Dict[str, Any]) -> Dict[str, Any]:
    """兼容旧调用；主动探测结果完整替换旧能力。"""
    return dict(fresh or {})

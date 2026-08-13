"""Safe, deterministic plan refinement for persistent PromptSession state."""
from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Iterator
from typing import Any, Iterable

from ..schemas.prompt_session import PromptSession, SessionFingerprints

class NodeExecutionResult(dict[str, Any]):
    """ComfyUI ui/result envelope that remains tuple-unpackable in Python callers."""

    def __iter__(self) -> Iterator[Any]:
        return iter(self.get("result", ()))


def node_execution_result(result: tuple[Any, ...], session_json: str,
                          current_prompt: str, change_summary: str,
                          revision: int,
                          validation_text: str = "") -> NodeExecutionResult:
    return NodeExecutionResult(
        result=result,
        ui={"prompt_session": [session_json],
            "current_prompt": [current_prompt],
            "change_summary": [change_summary],
            "revision": [str(revision)],
            "validation": [validation_text]},
    )


def message_identity(message_nonce: str, message: str) -> str:
    """Return an explicit UI nonce, or a deterministic legacy compatibility ID."""
    nonce = str(message_nonce or "").strip()
    if nonce:
        return nonce
    normalized = str(message or "").strip()
    if not normalized:
        return ""
    return "legacy_" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]


def content_fingerprint(value: Any) -> str:
    """Hash source state canonically without persisting raw objects in Session."""
    if value is None or value == "":
        return ""
    if hasattr(value, "to_json"):
        value = value.to_json()
    value = _fingerprint_payload(value)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _fingerprint_payload(value: Any) -> Any:
    """Remove volatile storage metadata while preserving authoritative source IDs."""
    volatile = {"created_at", "updated_at", "generated_at",
                "manifest_id", "plan_id", "raw", "validation", "warnings"}
    if isinstance(value, dict):
        return {key: _fingerprint_payload(item) for key, item in value.items()
                if key not in volatile}
    if isinstance(value, (list, tuple)):
        return [_fingerprint_payload(item) for item in value]
    return value


def component_fingerprint(*components: Any) -> str:
    """Hash the actual model-core/renderer components used by a target."""
    material: list[Any] = []
    for component in components:
        if callable(component):
            try:
                material.append(inspect.getsource(component))
            except (OSError, TypeError):
                material.append(getattr(component, "__qualname__", repr(component)))
        else:
            material.append(component)
    return content_fingerprint(material)


def media_fingerprint(value: Any) -> str:
    """Hash connected image/audio/video payloads without storing media in workflow state."""
    if value is None:
        return ""
    candidate = value
    if hasattr(candidate, "detach") and hasattr(candidate, "cpu"):
        candidate = candidate.detach().cpu()
    if hasattr(candidate, "numpy") and callable(candidate.numpy):
        try:
            candidate = candidate.numpy()
        except (TypeError, ValueError):
            pass
    if hasattr(candidate, "tobytes") and hasattr(candidate, "shape"):
        digest = hashlib.sha256()
        digest.update(str(tuple(candidate.shape)).encode("utf-8"))
        digest.update(str(getattr(candidate, "dtype", "")).encode("utf-8"))
        digest.update(candidate.tobytes(order="C"))
        return digest.hexdigest()
    if isinstance(candidate, (bytes, bytearray, memoryview)):
        return hashlib.sha256(bytes(candidate)).hexdigest()
    if isinstance(candidate, dict):
        return content_fingerprint({
            key: media_fingerprint(item) for key, item in sorted(candidate.items())})
    if isinstance(candidate, (list, tuple)):
        return content_fingerprint([media_fingerprint(item) for item in candidate])
    if hasattr(candidate, "to_json"):
        return content_fingerprint(candidate.to_json())
    if hasattr(candidate, "__dict__"):
        return content_fingerprint({
            "type": type(candidate).__qualname__, "state": vars(candidate)})
    return content_fingerprint({"type": type(candidate).__qualname__,
                                "value": str(candidate)})


def build_session_fingerprints(*, target_signature: str,
                               model_core_components: Iterable[Any],
                               sources: dict[str, Any] | None = None,
                               supplement_hashes: dict[str, str] | None = None
                               ) -> SessionFingerprints:
    source_hashes = {
        key: digest for key, value in sorted((sources or {}).items())
        if (digest := content_fingerprint(value))
    }
    return SessionFingerprints(
        target_signature=target_signature,
        model_core_hash=component_fingerprint(*model_core_components),
        source_hashes=source_hashes,
        supplement_hashes=dict(sorted((supplement_hashes or {}).items())))


def assert_session_fingerprints(session: PromptSession,
                                fingerprints: SessionFingerprints) -> None:
    mismatches = session.fingerprint_mismatches(fingerprints)
    if mismatches:
        raise ValueError(
            "Session 上下文指纹已变化，不能当作普通聊天修改。原因：" +
            "、".join(mismatches) + "。当前可执行：选择“新会话”；若已有至少"
            "两个成功版本，也可先恢复上一版。自动 Rebase 尚未实现；当前稳定 "
            f"revision v{session.revision} 保持不变。")

"""Safe, deterministic plan refinement for persistent PromptSession state."""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import logging
from collections.abc import Iterator
from typing import Any, Iterable

from ..schemas.profile import AIProfile
from ..schemas.prompt_session import PromptSession, SessionFingerprints
from ..schemas.changeset import ChangeSet
from .json_schema import make_strict_schema
from .structured_output import (
    bounded_issues,
    log_protocol_failure,
    protocol_failure_message,
    raw_excerpt,
)

logger = logging.getLogger("ai_prompt_studio.prompt_session")

REFINE_POLICY = """Apply the user's latest request to the current plan.
Change only the parts required to satisfy the latest request.
Preserve every unrelated decision, identity, subject, action, event, composition,
reference, and constraint. The current plan is the source of truth; the latest
user message describes only the requested delta. Return a reasoned semantic ChangeSet."""

# ``value_json`` keeps the provider-facing strict schema portable while the
# domain ChangeSet receives the decoded, typed JSON value before validation.
_WIRE_CHANGE = {"type": "object", "properties": {
    "path": {"type": "string"},
    "operation": {"type": "string", "enum": ["set", "delete", "insert"]},
    "value_json": {"type": "string"},
    "reason": {"type": "string"},
}}
CHANGESET_SCHEMA = make_strict_schema({
    "type": "object", "properties": {
        "base_revision": {"type": "integer"},
        "plan_type": {"type": "string"},
        "change_category": {"type": "string", "enum": [
            "minimal_refine", "broad_rewrite", "migration", "repair"]},
        "intent_scope": {"type": "array", "items": {"type": "string"}},
        "requested_changes": {"type": "array", "items": copy.deepcopy(_WIRE_CHANGE)},
        "dependent_changes": {"type": "array", "items": copy.deepcopy(_WIRE_CHANGE)},
        "invalidated_facts": {"type": "array", "items": {"type": "object",
            "properties": {"path": {"type": "string"}, "reason": {"type": "string"}}}},
        "constraint_conflicts": {"type": "array", "items": {"type": "object",
            "properties": {"path": {"type": "string"},
                           "constraint": {"type": "string"},
                           "reason": {"type": "string"}}}},
        "summary": {"type": "string"},
    },
})
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
                               skill_hashes: dict[str, str] | None = None
                               ) -> SessionFingerprints:
    source_hashes = {
        key: digest for key, value in sorted((sources or {}).items())
        if (digest := content_fingerprint(value))
    }
    return SessionFingerprints(
        target_signature=target_signature,
        model_core_hash=component_fingerprint(*model_core_components),
        source_hashes=source_hashes,
        skill_hashes=dict(sorted((skill_hashes or {}).items())))


def assert_session_fingerprints(session: PromptSession,
                                fingerprints: SessionFingerprints) -> None:
    mismatches = session.fingerprint_mismatches(fingerprints)
    if mismatches:
        raise ValueError(
            "Session 上下文指纹已变化，不能当作普通聊天修改。原因：" +
            "、".join(mismatches) + "。当前可执行：选择“新会话”；若已有至少"
            "两个成功版本，也可先恢复上一版。自动 Rebase 尚未实现；当前稳定 "
            f"revision v{session.revision} 保持不变。")


def request_changeset(gateway: Any, profile: AIProfile, api_key: str,
                      session: PromptSession, feedback: str,
                      runtime_constraints: dict[str, Any] | None = None) -> ChangeSet:
    """Request and decode the canonical P2 semantic ChangeSet contract."""
    import json

    from ..prompting.assembly import PromptLayer, PromptSource, StructuredTaskData
    from ..prompting.node_requests import assemble_prompt, report_payload, task_message
    from ..schemas.changeset import ConstraintConflict, InvalidatedFact, SemanticChange
    from .gateway import GenerateRequest
    from .reference import extract_json_object

    plan_type = session.target_family
    task_data = {
        "current_plan": _compact_semantic_plan(session),
        "locked_paths": _semantic_locked_paths(session),
        "latest_user_instruction": feedback,
        "base_revision": session.revision,
        "plan_type": plan_type,
        "authoritative_runtime_constraints": dict(runtime_constraints or {}),
    }
    policy = """Return one semantic ChangeSet, never a rewritten prompt or full plan.
First identify the explicitly requested changes. Then add only directly required
facts invalidated by the request. Preserve every unrelated field. Paths use slash
segments relative to the supplied current_plan object. Never prefix a path with current_plan,
model_plan, or h3_plan; never use dots or bracket notation. For example, use
content/characters/0/required_traits/3, not current_plan.content.characters[0].required_traits.
Use the smallest changed leaf or list item; do not replace a whole object or list merely
to edit one value. intent_scope must contain the exact requested paths or their real
slash-delimited parent paths, never conceptual labels such as color_adjustment.
dependent_changes must be []: trusted Python Impact Analysis adds provable dependencies;
put a possible consequence in invalidated_facts instead. Use minimal_refine unless the
user explicitly requests a broad redesign. Encode every change value as compact JSON in
value_json; use the literal string null for delete. Every change needs a specific reason.
Report hard conflicts instead of silently overriding them."""
    sources = [
        PromptSource("runtime.semantic-session", "2.0", PromptLayer.RUNTIME,
                     "Treat the supplied plan as stable structured state.",
                     "session.changeset"),
        PromptSource("operation.minimum-consistent-change", "2.0",
                     PromptLayer.OPERATION, REFINE_POLICY + "\n" + policy,
                     "session.changeset"),
    ]

    def make_request(retry_payload: dict[str, Any] | None = None) -> Any:
        retry_data = [StructuredTaskData("changeset_request", task_data)]
        if retry_payload is not None:
            retry_data.append(StructuredTaskData(
                "previous_protocol_failure", retry_payload))
        assembly = assemble_prompt(
            sources, task_data=retry_data,
            output_contract_id="semantic-changeset.schema@2")
        return GenerateRequest(
            system=assembly.system, messages=[task_message(assembly)],
            web_search="off", reasoning="medium", max_tokens=4096,
            timeout=profile.timeout, json_mode=True,
            output_schema=CHANGESET_SCHEMA,
            assembly_report=report_payload(assembly))

    def decode_change(item: Any) -> SemanticChange:
        if not isinstance(item, dict):
            raise ValueError("ChangeSet 变更项必须是对象")
        try:
            value = json.loads(str(item.get("value_json", "null")))
        except ValueError as exc:
            raise ValueError(f"ChangeSet value_json 不是合法 JSON: {item.get('path', '')}") from exc
        return SemanticChange(path=str(item.get("path", "")),
                              operation=str(item.get("operation", "")),
                              value=value, reason=str(item.get("reason", "")))

    changeset: ChangeSet | None = None
    retry_payload: dict[str, Any] | None = None
    last_raw_text = ""
    last_issues: list[str] = []
    for attempt in range(2):
        result = gateway.generate(profile, api_key, make_request(retry_payload))
        if result.has_error():
            raise ValueError(result.error.as_text)
        last_raw_text = result.text
        raw = extract_json_object(result.text)
        try:
            if not isinstance(raw, dict):
                raise ValueError("无法解析 JSON 对象")
            candidate = ChangeSet(
                base_revision=int(raw.get("base_revision", -1)),
                plan_type=str(raw.get("plan_type", "")),
                change_category=str(raw.get("change_category", "")),
                intent_scope=[str(item) for item in raw.get("intent_scope", [])],
                requested_changes=[decode_change(item)
                                   for item in raw.get("requested_changes", [])],
                dependent_changes=[decode_change(item)
                                   for item in raw.get("dependent_changes", [])],
                invalidated_facts=[InvalidatedFact.from_json(item)
                                   for item in raw.get("invalidated_facts", [])],
                constraint_conflicts=[ConstraintConflict.from_json(item)
                                      for item in raw.get("constraint_conflicts", [])],
                summary=str(raw.get("summary", "")))
            last_issues = bounded_issues(candidate.validate())
            if candidate.plan_type != plan_type:
                last_issues.append(
                    f"plan_type 不匹配: {candidate.plan_type!r} != {plan_type!r}")
            if candidate.base_revision != session.revision:
                last_issues.append(
                    f"revision 冲突：请求基于 {candidate.base_revision}，"
                    f"当前为 {session.revision}")
            valid_roots = set(task_data["current_plan"])
            declared_paths = [
                *[item.path for item in candidate.all_changes()],
                *candidate.intent_scope,
                *[item.path for item in candidate.invalidated_facts],
                *[item.path for item in candidate.constraint_conflicts],
            ]
            for path in declared_paths:
                root = str(path).strip().strip("/").split("/", 1)[0]
                if root and root not in valid_roots:
                    last_issues.append(
                        f"语义路径 {path!r} 的根 {root!r} 不属于 current_plan；"
                        f"可用根：{', '.join(sorted(valid_roots))}")
            for change in candidate.all_changes():
                path_issue = _proposal_path_issue(
                    task_data["current_plan"], change.path, change.operation)
                if path_issue:
                    last_issues.append(path_issue)
            last_issues = bounded_issues(last_issues)
            if last_issues:
                raise ValueError("；".join(last_issues))
            changeset = candidate
            break
        except (TypeError, ValueError) as exc:
            if not last_issues:
                last_issues = bounded_issues([exc])
            log_protocol_failure(
                logger, f"REFINE ChangeSet attempt {attempt + 1}",
                last_raw_text, last_issues)
            if attempt == 1:
                raise ValueError(protocol_failure_message(
                    "REFINE ChangeSet", last_raw_text, last_issues)) from exc
            retry_payload = {
                "instruction": "Correct the protocol errors only and return a new object.",
                "validation_errors": last_issues,
                "sanitized_previous_output": _sanitize_changeset_retry(raw),
                "raw_excerpt": raw_excerpt(last_raw_text),
            }
    if changeset is None:
        raise ValueError(protocol_failure_message(
            "REFINE ChangeSet", last_raw_text, last_issues))
    # ADR 0007 strict lane deliberately treats the declared requested paths as
    # mutation authority. Diff Guard, hard locks, deterministic dependency closure
    # and final validators constrain the candidate. Model-proposed dependencies
    # remain unapproved and are rejected by SemanticTransaction.
    changeset.approved_requested_paths = [
        item.path for item in changeset.requested_changes]
    changeset.approved_dependent_paths = []
    return changeset


def _sanitize_changeset_retry(raw: Any) -> dict[str, Any]:
    """Prepare bounded task data for one retry; never accept it as authority."""
    if not isinstance(raw, dict):
        return {}
    cleaned = copy.deepcopy(raw)
    seen: set[str] = set()
    for field in ("requested_changes", "dependent_changes"):
        unique: list[Any] = []
        values = cleaned.get(field, [])
        if not isinstance(values, list):
            cleaned[field] = []
            continue
        for item in values:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path", "")).strip()
            if not path or path in seen:
                continue
            seen.add(path)
            unique.append(item)
        cleaned[field] = unique
    scope = cleaned.get("intent_scope")
    if not isinstance(scope, list) or not any(str(item).strip() for item in scope):
        cleaned["intent_scope"] = [
            str(item.get("path", "")).strip()
            for item in cleaned.get("requested_changes", [])
            if isinstance(item, dict) and str(item.get("path", "")).strip()]
    return cleaned


def _compact_semantic_plan(session: PromptSession) -> dict[str, Any]:
    """Return the complete editable semantic shape, without derived/session state."""
    from ..domain.plan_adapters import get_session_plan_adapter

    adapter = get_session_plan_adapter(session.target_family)
    if session.target_family == "minimax_h3":
        raw = session.current_plan.get("h3_plan", {})
    else:
        model_plan = session.current_plan.get("model_plan", {})
        raw = {"content": model_plan.get("content", {}),
               "negative": model_plan.get("negative", "")}
    data = adapter.dump(adapter.load(raw))
    return _drop_semantic_metadata(data)


def _proposal_path_issue(root: dict[str, Any], path: str,
                         operation: str) -> str:
    """Return a protocol issue when a proposed mutation cannot address current Plan."""
    parts = [part for part in str(path).strip().strip("/").split("/") if part]
    if not parts:
        return f"语义路径 {path!r} 为空"
    target_parts = parts[:-1] if operation == "insert" else parts
    current: Any = root
    try:
        for part in target_parts:
            current = current[int(part)] if isinstance(current, list) else current[part]
    except (KeyError, IndexError, TypeError, ValueError):
        return f"语义路径 {path!r} 在 current_plan 中不存在"
    if operation == "insert":
        leaf = parts[-1]
        if (not isinstance(current, list) or not leaf.isdigit()
                or int(leaf) > len(current)):
            return f"insert 路径 {path!r} 不是 current_plan 中的有效列表索引"
    return ""


def _drop_semantic_metadata(value: Any) -> Any:
    excluded = {"schema_version", "normal_form_version", "plan_id", "created_at",
                "validation", "raw", "warnings", "operation", "storyboard_id"}
    if isinstance(value, dict):
        return {key: _drop_semantic_metadata(item)
                for key, item in value.items() if key not in excluded}
    if isinstance(value, list):
        return [_drop_semantic_metadata(item) for item in value]
    return value


def _semantic_locked_paths(session: PromptSession) -> list[str]:
    prefixes = ("model_plan/content/", "h3_plan/")
    paths: list[str] = []
    for raw in session.locked_constraints:
        value = str(raw).strip().strip("/")
        for prefix in prefixes:
            if value.startswith(prefix):
                value = value[len(prefix):]
                break
        if value:
            paths.append(value)
    return paths

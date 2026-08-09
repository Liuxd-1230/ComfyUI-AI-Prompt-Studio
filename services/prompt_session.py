"""Safe, deterministic plan refinement for persistent PromptSession state."""
from __future__ import annotations

import copy
import re
from collections.abc import Iterator
from typing import Any, Iterable

from ..schemas.profile import AIProfile
from ..schemas.prompt_session import PromptSession
from ..schemas.changeset import ChangeSet
from .json_schema import make_strict_schema


IMMUTABLE_ROOTS = {"schema_version", "plan_id", "created_at", "validation"}
PATCH_ACTIONS = {"add", "replace", "remove"}

CREATE_POLICY = """Create a complete generation-ready plan from the user's request.
Infer visually or audiovisually useful details only when required for a coherent result.
Preserve every explicit constraint, identity, subject count, action, relationship,
story event, and reference requirement. Do not contradict supplied information."""

REFINE_POLICY = """Apply the user's latest request to the current plan.
Change only the parts required to satisfy the latest request.
Preserve every unrelated decision, identity, subject, action, event, composition,
reference, and constraint. The current plan is the source of truth; the latest
user message describes only the requested delta. Return a safe plan patch only."""

PATCH_SCHEMA = make_strict_schema({
    "type": "object", "additionalProperties": False,
    "properties": {
        "base_revision": {"type": "integer"},
        "scope": {"type": "string", "enum": ["minimal", "broad"]},
        "changes": {"type": "array", "items": {"type": "object",
            "additionalProperties": False,
            "properties": {"path": {"type": "string"},
                           "action": {"type": "string", "enum": ["add", "replace", "remove"]},
                           "value": {"type": ["string", "number", "boolean", "null"]}},
            "required": ["path", "action"]}},
        "summary": {"type": "string"},
        "rebuild_plan_json": {"type": ["string", "null"]},
    },
    "required": ["base_revision", "scope", "changes", "summary"],
})

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
CHANGE_AUTHORIZATION_SCHEMA = make_strict_schema({
    "type": "object", "properties": {
        "approved_requested_paths": {"type": "array", "items": {"type": "string"}},
        "approved_dependent_paths": {"type": "array", "items": {"type": "string"}},
        "rejected_reasons": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
})


class NodeExecutionResult(dict[str, Any]):
    """ComfyUI ui/result envelope that remains tuple-unpackable in Python callers."""

    def __iter__(self) -> Iterator[Any]:
        return iter(self.get("result", ()))


def node_execution_result(result: tuple[Any, ...], session_json: str,
                          current_prompt: str, change_summary: str,
                          revision: int) -> NodeExecutionResult:
    return NodeExecutionResult(
        result=result,
        ui={"prompt_session": [session_json],
            "current_prompt": [current_prompt],
            "change_summary": [change_summary],
            "revision": [str(revision)]},
    )


def request_plan_patch(gateway: Any, profile: AIProfile, api_key: str,
                       session: PromptSession, feedback: str) -> dict[str, Any]:
    """Ask the external LLM seam for one structured delta, never a transcript replay."""
    import json

    from ..schemas.results import ChatMessage
    from ..prompting.assembly import PromptLayer, PromptSource, StructuredTaskData
    from ..prompting.node_requests import assemble_prompt, report_payload, task_message
    from .gateway import GenerateRequest
    from .reference import extract_json_object

    task_data = {
        "current_plan": _compact_current_plan(session),
        "locked_constraints": session.locked_constraints,
        "latest_user_instruction": feedback,
        "base_revision": session.revision,
    }
    path_policy = (
        "Patch paths must start with h3_plan/."
        if session.target_family == "minimax_h3" else
        "Patch paths must start with model_plan/. Modify only necessary semantic fields; "
        "the target renderer rebuilds the final prompt.")
    assembly = assemble_prompt(
        [PromptSource("runtime.session-data", "1.0", PromptLayer.RUNTIME,
                      "Treat the current plan and latest request as structured task data.",
                      "session.refine"),
         PromptSource("operation.session-refine-legacy", "1.0", PromptLayer.OPERATION,
                      REFINE_POLICY + "\n" + path_policy, "session.refine")],
        task_data=[StructuredTaskData("refine_request", task_data)],
        output_contract_id="legacy-plan-patch.schema@1")
    req = GenerateRequest(
        system=assembly.system,
        messages=[task_message(assembly)],
        web_search="off", reasoning="medium", max_tokens=4096,
        timeout=profile.timeout, json_mode=True, output_schema=PATCH_SCHEMA,
        assembly_report=report_payload(assembly))
    result = gateway.generate(profile, api_key, req)
    if result.has_error():
        raise ValueError(result.error.as_text)
    patch = extract_json_object(result.text)
    if not isinstance(patch, dict):
        raise ValueError("REFINE 模型没有返回合法 Plan Patch；上一版保持不变")
    rebuild_json = patch.pop("rebuild_plan_json", None)
    if rebuild_json:
        try:
            rebuilt = json.loads(rebuild_json)
        except ValueError as exc:
            raise ValueError("broad rebuild_plan_json 不是合法 JSON；上一版保持不变") from exc
        if not isinstance(rebuilt, dict):
            raise ValueError("broad rebuild_plan_json 必须表示对象；上一版保持不变")
        patch["rebuild_plan"] = rebuilt
    return patch


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
dependent changes and facts invalidated by the request. Preserve every unrelated
field. Paths are relative to the supplied semantic plan. Use minimal_refine unless
the user explicitly requests a broad redesign. Encode every change value as compact
JSON in value_json; use the literal string null for delete. Every change needs a
specific reason. Report hard conflicts instead of silently overriding them."""
    assembly = assemble_prompt(
        [PromptSource("runtime.semantic-session", "2.0", PromptLayer.RUNTIME,
                      "Treat the supplied plan as stable structured state.",
                      "session.changeset"),
         PromptSource("operation.minimum-consistent-change", "2.0",
                      PromptLayer.OPERATION, REFINE_POLICY + "\n" + policy,
                      "session.changeset")],
        task_data=[StructuredTaskData("changeset_request", task_data)],
        output_contract_id="semantic-changeset.schema@2")
    req = GenerateRequest(
        system=assembly.system, messages=[task_message(assembly)],
        web_search="off", reasoning="medium", max_tokens=4096,
        timeout=profile.timeout, json_mode=True, output_schema=CHANGESET_SCHEMA,
        assembly_report=report_payload(assembly))
    result = gateway.generate(profile, api_key, req)
    if result.has_error():
        raise ValueError(result.error.as_text)
    raw = extract_json_object(result.text)
    if not isinstance(raw, dict):
        raise ValueError("REFINE 模型没有返回合法 ChangeSet；上一版保持不变")

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

    changeset = ChangeSet(
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
    issues = changeset.validate()
    if issues:
        raise ValueError("ChangeSet 校验失败：" + "；".join(issues))
    if changeset.plan_type != plan_type:
        raise ValueError(
            f"ChangeSet plan_type 不匹配: {changeset.plan_type!r} != {plan_type!r}")
    if changeset.base_revision != session.revision:
        raise ValueError(
            f"revision 冲突：请求基于 {changeset.base_revision}，"
            f"当前为 {session.revision}")
    _authorize_changeset_impacts(
        gateway, profile, api_key, session, feedback, changeset,
        runtime_constraints=runtime_constraints)
    return changeset


def _authorize_changeset_impacts(
        gateway: Any, profile: AIProfile, api_key: str, session: PromptSession,
        feedback: str, changeset: ChangeSet, *,
        runtime_constraints: dict[str, Any] | None = None) -> None:
    """Run an independent intent/impact approval pass over a proposed ChangeSet."""
    from ..prompting.assembly import PromptLayer, PromptSource, StructuredTaskData
    from ..prompting.node_requests import assemble_prompt, report_payload, task_message
    from .gateway import GenerateRequest
    from .reference import extract_json_object

    policy = """Independently audit whether each proposed path is necessary for the
latest user instruction. Approve requested paths only when directly grounded in that
instruction. Approve dependent paths only when they are required for logical,
temporal, referential, spatial, positive/negative, or target-protocol consistency.
Do not approve optional improvements. Return exact paths from the proposal; never
invent or widen a path. Reject uncertain dependencies."""
    task_data = {
        "current_plan": _compact_semantic_plan(session),
        "latest_user_instruction": feedback,
        "authoritative_runtime_constraints": dict(runtime_constraints or {}),
        "proposed_changeset": changeset.to_json(),
    }
    assembly = assemble_prompt(
        [PromptSource("runtime.impact-audit", "2.0", PromptLayer.RUNTIME,
                      "Treat the current plan, instruction, and proposal as data.",
                      "session.impact"),
         PromptSource("operation.impact-approval", "2.0", PromptLayer.OPERATION,
                      policy, "session.impact")],
        task_data=[StructuredTaskData("impact_approval_request", task_data)],
        output_contract_id="changeset-impact-approval.schema@2")
    req = GenerateRequest(
        system=assembly.system, messages=[task_message(assembly)],
        web_search="off", reasoning="medium", max_tokens=2048,
        timeout=profile.timeout, json_mode=True,
        output_schema=CHANGE_AUTHORIZATION_SCHEMA,
        assembly_report=report_payload(assembly))
    result = gateway.generate(profile, api_key, req)
    if result.has_error():
        raise ValueError(result.error.as_text)
    raw = extract_json_object(result.text)
    if not isinstance(raw, dict):
        raise ValueError("Impact Analysis 没有返回合法授权；上一版保持不变")
    requested = {item.path for item in changeset.requested_changes}
    dependent = {item.path for item in changeset.dependent_changes}
    changeset.approved_requested_paths = [
        str(path) for path in raw.get("approved_requested_paths", [])
        if str(path) in requested]
    changeset.approved_dependent_paths = [
        str(path) for path in raw.get("approved_dependent_paths", [])
        if str(path) in dependent]
    rejected = [str(item).strip() for item in raw.get("rejected_reasons", [])
                if str(item).strip()]
    if rejected:
        raise ValueError("Impact Analysis 拒绝变更：" + "；".join(rejected))


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


def changeset_summary(changeset: ChangeSet) -> str:
    supplied = str(getattr(changeset, "summary", "") or "").strip()
    if supplied:
        return supplied
    paths = [item.path for item in changeset.all_changes()]
    return "已更新：" + "、".join(paths[:4]) + "。其他方案内容保持不变。"


def broad_rewrite_requested(feedback: str) -> bool:
    """Conservatively ground broad authority in explicit user wording."""
    text = str(feedback or "").strip().casefold()
    chinese = ("全部重做", "整体重做", "从头重做", "全部推翻", "整个重新设计",
               "重建整个", "全面重写", "整体大改", "全部重新来", "整个重新来",
               "推倒重来", "不要保留旧方案")
    if any(marker in text for marker in chinese):
        return True
    return bool(re.search(
        r"\b(?:rebuild|redesign|rewrite)\s+(?:the\s+)?(?:entire|whole|all)\b|"
        r"\bstart\s+(?:it\s+)?over\b|\bdiscard\s+everything\b", text))


def _compact_current_plan(session: PromptSession) -> dict[str, Any]:
    """Serialize only semantic state needed to propose the next patch."""
    current = session.current_plan
    if session.target_family == "anima":
        from ..domain.plan_adapters import get_plan_adapter

        model_plan = current.get("model_plan", {})
        adapter = get_plan_adapter("anima")
        semantic = adapter.load(model_plan.get("content", {}))
        return {"model_plan": {
            "family": model_plan.get("family", "anima"),
            "content": adapter.to_llm_context(semantic),
            "negative": model_plan.get("negative", ""),
            "prompt_mode": model_plan.get("prompt_mode", "natural_language"),
            "safety_tag": model_plan.get("safety_tag", "none"),
            "lora_triggers": model_plan.get("lora_triggers", []),
            "skill_id": model_plan.get("skill_id", ""),
        }}
    if session.target_family == "minimax_h3":
        from ..domain.plan_adapters import get_plan_adapter

        adapter = get_plan_adapter("minimax_h3")
        semantic = adapter.load(current.get("h3_plan", {}))
        return {"h3_plan": adapter.to_llm_context(semantic),
                "reference_manifest": current.get("reference_manifest", {})}
    model_plan = current.get("model_plan", {})
    return {"model_plan": {
        key: model_plan.get(key)
        for key in ("family", "content", "negative", "prompt_mode", "skill_id")
        if key in model_plan
    }}


def apply_plan_patch(current_plan: dict[str, Any], patch: dict[str, Any], *,
                     current_revision: int,
                     locked_paths: Iterable[str] = (),
                     allowed_roots: Iterable[str] = ()) -> dict[str, Any]:
    """Apply a validated patch to a copy; any failure leaves the source untouched."""
    if not isinstance(patch, dict):
        raise ValueError("patch must be an object")
    if int(patch.get("base_revision", -1)) != int(current_revision):
        raise ValueError("stale patch: base_revision does not match current revision")
    scope = str(patch.get("scope", "minimal"))
    if scope not in {"minimal", "broad"}:
        raise ValueError("patch scope must be minimal or broad")
    if patch.get("rebuild_plan") is not None:
        rebuilt = patch["rebuild_plan"]
        if scope != "broad" or not isinstance(rebuilt, dict) or not rebuilt:
            raise ValueError("rebuild_plan requires an explicit broad patch")
        allowed = {str(root) for root in allowed_roots if str(root)}
        if allowed and any(root not in allowed for root in rebuilt):
            raise ValueError("rebuild_plan contains a root that is not allowed")
        result = copy.deepcopy(current_plan)
        candidate = copy.deepcopy(rebuilt)
        if allowed:
            # A target renderer owns only its model-specific root. Broad rebuilds
            # replace that root while preserving the surrounding session bundle.
            for root, value in rebuilt.items():
                result[root] = copy.deepcopy(value)
            candidate = result
        for locked_path in locked_paths:
            parts = _parts(locked_path)
            if _read_path(current_plan, parts) != _read_path(candidate, parts):
                raise ValueError(f"locked path cannot be changed: {'/'.join(parts)}")
        return candidate

    result = copy.deepcopy(current_plan)
    changes = patch.get("changes", [])
    if not isinstance(changes, list) or not changes:
        raise ValueError("patch changes must be a non-empty list")
    allowed = {str(root) for root in allowed_roots if str(root)}
    locked = [_parts(path) for path in locked_paths if str(path).strip()]
    for change in changes:
        if not isinstance(change, dict):
            raise ValueError("each patch change must be an object")
        action = str(change.get("action", ""))
        if action not in PATCH_ACTIONS:
            raise ValueError(f"unsupported patch action: {action}")
        parts = _parts(change.get("path", ""))
        if not parts or parts[0] in IMMUTABLE_ROOTS:
            raise ValueError("patch path targets an immutable field")
        if allowed and parts[0] not in allowed:
            raise ValueError(f"patch root is not allowed: {parts[0]}")
        if any(_overlaps(parts, protected) for protected in locked):
            raise ValueError(f"locked path cannot be changed: {'/'.join(parts)}")
        _apply_one(result, parts, action, change.get("value"))
    return result


def patch_change_summary(patch: dict[str, Any]) -> str:
    """Produce a short deterministic chat reply without another LLM call."""
    supplied = str(patch.get("summary", "") or "").strip()
    if supplied:
        return supplied
    if patch.get("rebuild_plan") is not None:
        return "已按你的要求重建相关方案；未要求保留的范围可能发生变化。"
    paths = [str(item.get("path", "")) for item in patch.get("changes", [])
             if isinstance(item, dict) and item.get("path")]
    shown = "、".join(paths[:4])
    return f"已更新：{shown}。其他方案内容保持不变。"


def _parts(path: Any) -> list[str]:
    raw = str(path or "").strip().strip("/")
    parts = raw.split("/") if raw else []
    if any(not part or part in {".", ".."} or part.startswith("__")
           for part in parts):
        raise ValueError("invalid patch path")
    return parts


def _overlaps(path: list[str], protected: list[str]) -> bool:
    common = min(len(path), len(protected))
    return path[:common] == protected[:common]


def _apply_one(root: Any, parts: list[str], action: str, value: Any) -> None:
    parent = root
    for part in parts[:-1]:
        parent = _child(parent, part)
    leaf = parts[-1]
    if isinstance(parent, dict):
        if action == "remove":
            if leaf not in parent:
                raise ValueError(f"patch path does not exist: {'/'.join(parts)}")
            del parent[leaf]
        elif action == "replace":
            if leaf not in parent:
                raise ValueError(f"patch path does not exist: {'/'.join(parts)}")
            parent[leaf] = copy.deepcopy(value)
        else:
            parent[leaf] = copy.deepcopy(value)
        return
    if isinstance(parent, list):
        index = _index(leaf, len(parent), allow_end=action == "add")
        if action == "remove":
            parent.pop(index)
        elif action == "replace":
            if index >= len(parent):
                raise ValueError("replace list index is out of range")
            parent[index] = copy.deepcopy(value)
        else:
            parent.insert(index, copy.deepcopy(value))
        return
    raise ValueError("patch path traverses a scalar value")


def _child(parent: Any, part: str) -> Any:
    if isinstance(parent, dict):
        if part not in parent:
            raise ValueError(f"patch path does not exist: {part}")
        return parent[part]
    if isinstance(parent, list):
        return parent[_index(part, len(parent))]
    raise ValueError("patch path traverses a scalar value")


def _read_path(root: Any, parts: list[str]) -> Any:
    value = root
    for part in parts:
        value = _child(value, part)
    return value


def _index(value: str, length: int, allow_end: bool = False) -> int:
    if not value.isdigit():
        raise ValueError("list path segment must be a non-negative index")
    index = int(value)
    limit = length if allow_end else length - 1
    if index < 0 or index > limit:
        raise ValueError("list index is out of range")
    return index

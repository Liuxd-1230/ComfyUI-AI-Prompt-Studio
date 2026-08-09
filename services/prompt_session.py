"""Safe, deterministic plan refinement for persistent PromptSession state."""
from __future__ import annotations

import copy
from collections.abc import Iterator
from typing import Any, Iterable

from ..schemas.profile import AIProfile
from ..schemas.prompt_session import PromptSession
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
        "current_plan": session.current_plan,
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

"""ADR 0007 Image Prompt Studio with lenient and strict execution lanes."""
from __future__ import annotations

import json
import re
from typing import Any

from ..prompting.assembly import PromptLayer, PromptSource, StructuredTaskData
from ..prompting.node_requests import assemble_prompt, report_payload, task_message
from ..prompting.studio_policies import (
    FORMAT_REPAIR_POLICY,
    LENIENT_CREATE_POLICY,
    LENIENT_OUTPUT_CONTRACT,
    LENIENT_REFINE_POLICY,
    EXTERNAL_SKILL_BOUNDARY,
    external_skill_hashes,
    external_skill_task_payload,
    image_target_policy,
)
from ..renderers.anima import ANIMA_BASE_NEGATIVE, ANIMA_QUALITY_NEGATIVE
from ..renderers.anima import render_anima_plan
from ..renderers.generic import render_generic
from ..renderers.special_image import render_special_image
from ..domain.impact_analysis import analyze_image_impacts, validate_image_candidate
from ..domain.plan_adapters import get_session_plan_adapter
from ..domain.transactions import SemanticTransaction
from ..schemas.anima import AnimaPromptPlan
from ..schemas.image_semantic_plan import ImageSemanticPlan
from ..schemas.text_prompt import TextPromptPlan
from ..schemas import types
from ..schemas.character import CharacterBible, CharacterBook
from ..schemas.profile import AIProfile
from ..schemas.prompt_plan import ValidationReport
from ..schemas.prompt_session import PromptSession, SessionFingerprints
from ..schemas.references import ReferenceManifest
from ..services.gateway import Gateway, GenerateRequest
from ..services.prompt_protocol import LenientPromptOutput, parse_lenient_output
from ..services.recovery import get_recovery_journal
from ..services.prompt_session import (
    assert_session_fingerprints,
    build_session_fingerprints,
    message_identity,
    node_execution_result,
    request_changeset,
)
from ..services.structured_output import raw_excerpt
from ..services.reference import extract_json_object
from ..validators.anima import anima_english_issue, validate_anima
from ._helpers import require_api_key, resolve_profile_input


EXECUTION_MODES = ["lenient", "strict"]
TARGET_OPTIONS = [
    "anima_base", "anima_aesthetic", "anima_turbo",
    "z_image_turbo", "qwen_image_edit_2511", "generic_image",
]

_STRING_ARRAY = {"type": "array", "items": {"type": "string"}}
_ANIMA_CHARACTER_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "character_id": {"type": "string", "description": "Stable unique identifier."},
        "name": {"type": "string", "description": "Display name only."},
        "required_traits": {**_STRING_ARRAY, "description":
            "Stable visible appearance facts owned only here; no style, action, or position."},
        "variable_traits": {**_STRING_ARRAY, "description":
            "Optional changeable visible appearance facts owned only here."},
        "action": {"type": "string", "description": "Observable behavior owned only here."},
        "position": {"type": "string", "description": "Frame placement owned only here."},
        "creative_notes": {**_STRING_ARRAY, "description":
            "Return [] unless a character fact cannot fit traits, action, or position; never repeat."},
    },
    "required": ["character_id", "name", "required_traits", "variable_traits",
                 "action", "position", "creative_notes"],
}
_ANIMA_CONTENT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "scene_description": {"type": "string", "description":
            "Only residual drawable scene prose not owned by characters, environment, composition, lighting, or style. Usually return an empty string."},
        "creative_notes": {**_STRING_ARRAY, "description":
            "Return [] unless a unique drawable fact fits no structured field; never repeat."},
        "characters": {"type": "array", "items": _ANIMA_CHARACTER_SCHEMA},
        "control_tags": {**_STRING_ARRAY, "description":
            "Return [] for natural-language Studio; never duplicate prose or structured facts."},
        "series_tags": {**_STRING_ARRAY, "description":
            "Return [] for natural-language Studio unless an explicit unique series token is required."},
        "artist_tags": {**_STRING_ARRAY, "description":
            "Return [] for natural-language Studio unless an explicit unique artist token is required."},
        "supplemental_tags": {**_STRING_ARRAY, "description":
            "Return [] for natural-language Studio; never duplicate another field."},
        "style": {**_STRING_ARRAY, "description":
            "Rendering and aesthetic style facts owned only here."},
        "environment": {**_STRING_ARRAY, "description":
            "Location, weather, physical setting, and background facts owned only here."},
        "composition": {"type": "string", "description":
            "Framing, camera viewpoint, layout, and spatial composition owned only here."},
        "lighting": {"type": "string", "description":
            "Light sources, color, direction, contrast, and exposure owned only here."},
        "negative_constraints": {**_STRING_ARRAY, "description":
            "Negative-only constraints. These are not positive scene facts."},
    },
    "required": ["scene_description", "creative_notes", "characters",
                 "control_tags", "series_tags", "artist_tags",
                 "supplemental_tags", "style", "environment", "composition",
                 "lighting", "negative_constraints"],
}
_TEXT_CONTENT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"clauses": {
        "type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"text": {"type": "string"},
                           "separator": {"type": "string"}},
            "required": ["text", "separator"],
        }}},
    "required": ["clauses"],
}


class APS_PromptStudio:
    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {"required": {
            "AI_PROFILE": (types.AI_PROFILE,),
            "text": ("STRING", {"default": "", "multiline": True,
                                "tooltip": "第一次写生成要求；之后只写本轮修改意见"}),
            "target": (TARGET_OPTIONS, {"default": "anima_base"}),
            "execution_mode": (EXECUTION_MODES, {"default": "lenient",
                                "tooltip": "lenient=稳定提示词改写；strict=结构化事务"}),
            "session_action": (["continue", "previous", "new"],
                               {"default": "continue"}),
        }, "optional": {
            "story_item": (types.STORY_ITEM,),
            "character_bible": (types.CHARACTER_BIBLE,),
            "character_book": (types.CHARACTER_BOOK,),
            "reference_manifest": (types.REFERENCE_MANIFEST,),
            "prompt_session": ("STRING", {"default": "", "multiline": True}),
            "message_nonce": ("STRING", {"default": "", "multiline": False}),
        }, "hidden": {"unique_id": "UNIQUE_ID"}}

    RETURN_TYPES = ("STRING", "STRING", types.PROMPT_SESSION, "STRING", "STRING")
    RETURN_NAMES = ("positive", "negative", "prompt_session", "validation",
                    "change_summary")
    FUNCTION = "run"
    CATEGORY = "AI Prompt Studio"
    OUTPUT_NODE = True
    DESCRIPTION = "默认宽松、可选严格的持续图像提示词工作台。"

    def run(self, AI_PROFILE: Any, text: str, target: str,
            execution_mode: str = "lenient", session_action: str = "continue",
            story_item: Any = None, character_bible: Any = None,
            character_book: Any = None, reference_manifest: Any = None,
            prompt_session: str = "", message_nonce: str = "",
            unique_id: Any = None) -> Any:
        if execution_mode not in EXECUTION_MODES:
            raise ValueError("execution_mode 必须是 lenient 或 strict")
        if execution_mode == "strict":
            return self._run_strict(
                AI_PROFILE, text, target, session_action, story_item,
                character_bible, character_book, reference_manifest,
                prompt_session, message_nonce, unique_id)
        return self._run_lenient(
            AI_PROFILE, text, target, session_action, story_item,
            character_bible, character_book, reference_manifest,
            prompt_session, message_nonce, unique_id)

    def _run_lenient(
            self, AI_PROFILE: Any, text: str, target: str, session_action: str,
            story_item: Any, character_bible: Any, character_book: Any,
            reference_manifest: Any, prompt_session: str,
            message_nonce: str, unique_id: Any = None) -> Any:
        incoming = AIProfile.from_json(AI_PROFILE or {})
        if not incoming.profile_id:
            raise ValueError("未收到 AI_PROFILE：请先连接 AI Model Profile 节点")
        profile = resolve_profile_input(AI_PROFILE)
        api_key = require_api_key(profile)
        family, variant = _split_target(target)
        session = (PromptSession.from_json(prompt_session)
                   if prompt_session else PromptSession())
        node_id = str(unique_id or "").strip()
        journal = get_recovery_journal() if node_id else None
        if node_id:
            session, _ = session.for_node(node_id)
        if session_action == "new" or (
                session.has_current_state and session.execution_mode != "lenient"):
            session = PromptSession(
                target_family=family, target_variant=variant,
                execution_mode="lenient", node_instance_id=node_id)
        if session_action == "previous":
            if not session.revert_previous(
                    node_instance_id=node_id, recovery_journal=journal):
                raise ValueError("当前会话尚无可恢复的成功版本；至少需要两个成功 revision")
            return self._freeform_result(session, "已恢复上一版提示词。")
        if not session.has_current_state:
            session.target_family, session.target_variant = family, variant
        instruction = _input_text(text, story_item)
        if not instruction.strip():
            if session.has_current_state:
                return self._freeform_result(
                    session, "没有新的消息；沿用当前提示词，未调用模型。")
            raise ValueError("text 与 story_item 均为空，请至少提供一个")
        message_id = message_identity(message_nonce, instruction)
        if session.has_current_state and session.has_processed_message(message_id):
            return self._freeform_result(
                session, "没有新的消息；沿用当前提示词，未调用模型。")

        bible, book = _character_sources(character_bible, character_book)
        manifest = (ReferenceManifest.from_json(reference_manifest)
                    if reference_manifest else ReferenceManifest())
        fingerprints = build_session_fingerprints(
            target_signature=f"{family}:{variant}:lenient",
            model_core_components=("image-studio-lenient", family, variant,
                                   image_target_policy(family, variant)),
            sources={"story_item": story_item, "character_bible": bible,
                     "character_book": book, "reference_manifest": manifest},
            skill_hashes=external_skill_hashes(family, variant))
        context_changes = (session.fingerprints.mismatches(fingerprints)
                           if session.has_current_state else [])
        current_prompt = session.current_prompt if session.has_current_state else ""
        raw = self._generate_lenient(
            profile, api_key, family, variant, instruction, current_prompt,
            bible, book, manifest)
        parsed = parse_lenient_output(raw)
        report = _validate_lenient_image(
            parsed, family, variant, bible, book, manifest)
        repair_count = 0
        if parsed.kind == "protocol_garbage" or not report.valid:
            repair_count = 1
            raw = self._repair_lenient(
                profile, api_key, family, variant, raw,
                [*parsed.issues, *[issue.message for issue in report.issues]])
            parsed = parse_lenient_output(raw)
            report = _validate_lenient_image(
                parsed, family, variant, bible, book, manifest)
        if parsed.kind == "protocol_garbage" or not report.valid:
            detail = report.as_text() if report.issues else "；".join(parsed.issues)
            raise ValueError(
                "宽松提示词在一次格式修复后仍不可用；上一版保持不变：\n" + detail)
        for warning in parsed.warnings:
            report.add("warning", "lenient_untagged_prompt", warning)
        for change in context_changes:
            report.add("warning", "lenient_context_changed",
                       f"上下文已变化但宽松模式继续执行：{change}")
        summary = parsed.summary or (
            "已根据本轮要求更新提示词。" if session.has_current_state
            else "已创建第一版提示词。")
        session.target_family, session.target_variant = family, variant
        session.commit(
            {}, parsed.prompt, report, instruction, summary,
            expected_revision=session.revision, message_id=message_id,
            fingerprints=fingerprints, repair_count=repair_count,
            execution_mode="lenient", payload_kind="freeform",
            context_changes=context_changes, node_instance_id=node_id,
            recovery_journal=journal)
        negative = _negative_for(family, variant)
        result = (parsed.prompt, negative, session.to_json_string(),
                  report.as_text(), summary)
        return node_execution_result(
            result, session.to_json_string(), parsed.prompt, summary,
            session.revision, report.as_text())

    def _generate_lenient(
            self, profile: Any, api_key: str, family: str, variant: str,
            instruction: str, current_prompt: str, bible: CharacterBible | None,
            book: CharacterBook | None, manifest: ReferenceManifest) -> str:
        operation = LENIENT_REFINE_POLICY if current_prompt else LENIENT_CREATE_POLICY
        sources = [
            PromptSource("runtime.studio-lenient", "1.0", PromptLayer.RUNTIME,
                         LENIENT_OUTPUT_CONTRACT + "\n\n" + EXTERNAL_SKILL_BOUNDARY,
                         "prompt-studio"),
            PromptSource("model.image-target", "1.0", PromptLayer.MODEL_CORE,
                         image_target_policy(family, variant), "prompt-studio"),
            PromptSource("operation.refine" if current_prompt else "operation.create",
                         "1.0", PromptLayer.OPERATION, operation, "prompt-studio"),
        ]
        task_data = [StructuredTaskData("latest_instruction", instruction,
                                        "text/plain")]
        skill_data = external_skill_task_payload(family, variant)
        if skill_data is not None:
            task_data.append(StructuredTaskData("external_skill_guidance", skill_data))
        if current_prompt:
            task_data.append(StructuredTaskData(
                "current_prompt", current_prompt, "text/plain"))
        task_data.extend(_source_task_data(bible, book, manifest))
        assembly = assemble_prompt(
            sources, task_data=task_data,
            output_contract_id="lenient-tagged-prompt@1")
        request = GenerateRequest(
            system=assembly.system, messages=[task_message(assembly)],
            web_search="off", reasoning=profile.reasoning,
            max_tokens=4096, timeout=profile.timeout,
            assembly_report=report_payload(assembly))
        result = Gateway().generate(profile, api_key, request)
        if result.has_error():
            raise ValueError(result.error.as_text)
        return result.text

    def _repair_lenient(
            self, profile: Any, api_key: str, family: str, variant: str,
            raw: str, issues: list[str]) -> str:
        assembly = assemble_prompt(
            [PromptSource("runtime.studio-lenient", "1.0", PromptLayer.RUNTIME,
                          LENIENT_OUTPUT_CONTRACT + "\n\n" + EXTERNAL_SKILL_BOUNDARY,
                          "prompt-studio"),
             PromptSource("model.image-target", "1.0", PromptLayer.MODEL_CORE,
                          image_target_policy(family, variant), "prompt-studio"),
             PromptSource("operation.format-repair", "1.0", PromptLayer.OPERATION,
                          FORMAT_REPAIR_POLICY, "prompt-studio")],
            task_data=[StructuredTaskData("rejected_output", raw, "text/plain"),
                       StructuredTaskData("concrete_issues", issues),
                       *([StructuredTaskData("external_skill_guidance", skill_data)]
                         if (skill_data := external_skill_task_payload(family, variant))
                         is not None else [])],
            output_contract_id="lenient-tagged-prompt@1")
        request = GenerateRequest(
            system=assembly.system, messages=[task_message(assembly)],
            web_search="off", reasoning="low", max_tokens=4096,
            timeout=profile.timeout,
            assembly_report=report_payload(assembly))
        result = Gateway().generate(profile, api_key, request)
        if result.has_error():
            raise ValueError(result.error.as_text)
        return result.text

    def _run_strict(
            self, AI_PROFILE: Any, text: str, target: str, session_action: str,
            story_item: Any, character_bible: Any, character_book: Any,
            reference_manifest: Any, prompt_session: str,
            message_nonce: str, unique_id: Any = None) -> Any:
        incoming = AIProfile.from_json(AI_PROFILE or {})
        if not incoming.profile_id:
            raise ValueError("未收到 AI_PROFILE：请先连接 AI Model Profile 节点")
        profile = resolve_profile_input(AI_PROFILE)
        api_key = require_api_key(profile)
        family, variant = _split_target(target)
        stable = (PromptSession.from_json(prompt_session)
                  if prompt_session else PromptSession())
        node_id = str(unique_id or "").strip()
        journal = get_recovery_journal() if node_id else None
        if node_id:
            stable, _ = stable.for_node(node_id)
        starts_new = (session_action == "new" or
                      (stable.has_current_state
                       and stable.execution_mode != "strict"))
        session = (PromptSession(target_family=family, target_variant=variant,
                                 execution_mode="strict",
                                 node_instance_id=node_id)
                   if starts_new else stable)
        bible, book = _character_sources(character_bible, character_book)
        manifest = (ReferenceManifest.from_json(reference_manifest)
                    if reference_manifest else ReferenceManifest())
        fingerprints = build_session_fingerprints(
            target_signature=f"{family}:{variant}:strict",
            model_core_components=("image-studio-strict", family, variant,
                                   image_target_policy(family, variant)),
            sources={"story_item": story_item, "character_bible": bible,
                     "character_book": book, "reference_manifest": manifest},
            skill_hashes=external_skill_hashes(family, variant))
        if session_action == "previous" and not starts_new:
            assert_session_fingerprints(session, fingerprints)
            if not session.revert_previous(
                    node_instance_id=node_id, recovery_journal=journal):
                raise ValueError("当前会话尚无可恢复的成功版本；至少需要两个成功 revision")
            return self._strict_result(session, "已恢复上一版结构化提示词。")
        instruction = _input_text(text, story_item)
        if session.has_current_state:
            assert_session_fingerprints(session, fingerprints)
        if not instruction.strip():
            if session.has_current_state:
                return self._strict_result(
                    session, "没有新的消息；沿用当前提示词，未调用模型。")
            raise ValueError("text 与 story_item 均为空，请至少提供一个")
        message_id = message_identity(message_nonce, instruction)
        if session.has_current_state and session.has_processed_message(message_id):
            return self._strict_result(
                session, "没有新的消息；沿用当前提示词，未调用模型。")
        if not session.has_current_plan:
            session.target_family, session.target_variant = family, variant
            plan, repair_count = self._create_strict_plan(
                profile, api_key, family, variant, instruction,
                bible, book, manifest)
            summary = "已创建第一版严格结构化提示词。"
            changeset = None
        else:
            changeset = request_changeset(
                Gateway(), profile, api_key, session, instruction)
            adapter = get_session_plan_adapter(family)
            current = adapter.load(session.current_plan.get("model_plan", {}))
            tx = SemanticTransaction(adapter).execute(
                current, changeset, current_revision=session.revision,
                impact_analyzer=analyze_image_impacts,
                semantic_check=validate_image_candidate,
                allowed_roots=("content", "negative"),
                locked_paths=tuple(session.locked_constraints),
                broad_only_roots=("content",),
                allow_broad=changeset.change_category == "broad_rewrite")
            plan = tx.plan
            repair_count = 0
            summary = changeset.summary
        positive, negative, report = _render_validate_strict_image(
            plan, family, variant, bible, book, manifest)
        if not report.valid:
            raise ValueError(
                "严格模式校验未通过；上一版保持不变：\n" + report.as_text())
        current_plan = {"model_plan": plan.to_json()}
        session.commit(
            current_plan, positive, report, instruction, summary,
            expected_revision=session.revision, message_id=message_id,
            fingerprints=fingerprints, execution_mode="strict",
            payload_kind="structured", repair_count=repair_count,
            requested_paths=([item.path for item in changeset.requested_changes]
                             if changeset else []),
            dependent_paths=([item.path for item in changeset.dependent_changes]
                             if changeset else []),
            invalidated_paths=([item.path for item in changeset.invalidated_facts]
                               if changeset else []),
            renderer_signature=f"{family}:{variant}:strict",
            node_instance_id=node_id, recovery_journal=journal)
        result = (positive, negative, session.to_json_string(),
                  report.as_text(), summary)
        return node_execution_result(
            result, session.to_json_string(), positive, summary, session.revision,
            report.as_text())

    def _create_strict_plan(
            self, profile: Any, api_key: str, family: str, variant: str,
            instruction: str, bible: CharacterBible | None,
            book: CharacterBook | None,
            manifest: ReferenceManifest) -> tuple[ImageSemanticPlan, int]:
        schema = _strict_image_schema(family)
        task_data = [StructuredTaskData("latest_instruction", instruction,
                                        "text/plain")]
        skill_data = external_skill_task_payload(family, variant)
        if skill_data is not None:
            task_data.append(StructuredTaskData("external_skill_guidance", skill_data))
        task_data.extend(_source_task_data(bible, book, manifest))
        raw = ""
        issues: list[str] = []
        for attempt in range(2):
            operation = (
                "Create a normalized semantic image plan. Put each fact in exactly "
                "one field. For ANIMA: characters[].required_traits owns stable visible "
                "appearance; action owns behavior; position owns frame placement; "
                "environment owns location/weather/physical setting; lighting owns light; "
                "composition owns framing/camera/layout; style owns rendering style. "
                "scene_description owns only residual scene prose that belongs to none of "
                "those fields. Usually leave creative_notes and all tag arrays empty; use "
                "them only for a unique fact absent from every other field. Never repeat a "
                "word, phrase, or paraphrased fact across prose, traits, tags, or notes. "
                "Return only the schema object; never return rendered prose."
                if attempt == 0 else
                "Correct only the listed JSON/schema protocol defects. Preserve all "
                "usable facts from the rejected output; do not redesign the request.")
            retry_data = list(task_data)
            if attempt:
                retry_data.extend([
                    StructuredTaskData("rejected_output", raw, "text/plain"),
                    StructuredTaskData("protocol_issues", issues),
                ])
            assembly = assemble_prompt(
                [PromptSource("runtime.studio-strict", "1.0", PromptLayer.RUNTIME,
                              "Strict mode stores typed semantic state.\n\n" +
                              EXTERNAL_SKILL_BOUNDARY, "prompt-studio"),
                 PromptSource("model.image-target", "1.0", PromptLayer.MODEL_CORE,
                              image_target_policy(family, variant), "prompt-studio"),
                 PromptSource("operation.strict-create", "1.0",
                              PromptLayer.OPERATION, operation, "prompt-studio")],
                task_data=retry_data,
                output_contract_id="image-semantic-plan.schema@1")
            request = GenerateRequest(
                system=assembly.system, messages=[task_message(assembly)],
                web_search="off", reasoning=profile.reasoning,
                max_tokens=4096, timeout=profile.timeout, json_mode=True,
                output_schema=schema, assembly_report=report_payload(assembly))
            result = Gateway().generate(profile, api_key, request)
            if result.has_error():
                raise ValueError(result.error.as_text)
            raw = result.text
            try:
                parsed = extract_json_object(raw)
                if not isinstance(parsed, dict):
                    raise ValueError("没有可解析的 JSON 对象")
                return _load_strict_image_plan(parsed, family), attempt
            except (TypeError, ValueError) as exc:
                issues = [str(exc)]
        raise ValueError(
            "严格模式结构化协议在一次修复后仍不可用；上一版保持不变：" +
            "；".join(issues) + "。模型原始输出（截断）：" + raw_excerpt(raw))

    @staticmethod
    def _strict_result(session: PromptSession, summary: str) -> Any:
        plan = ImageSemanticPlan.from_json(
            session.current_plan.get("model_plan", {}))
        negative = plan.negative
        result = (session.current_prompt, negative, session.to_json_string(),
                  session.validation.as_text(), summary)
        return node_execution_result(
            result, session.to_json_string(), session.current_prompt, summary,
            session.revision, session.validation.as_text())

    @staticmethod
    def _freeform_result(session: PromptSession, summary: str) -> Any:
        negative = _negative_for(session.target_family, session.target_variant)
        result = (session.current_prompt, negative, session.to_json_string(),
                  session.validation.as_text(), summary)
        return node_execution_result(
            result, session.to_json_string(), session.current_prompt, summary,
            session.revision, session.validation.as_text())


def _split_target(target: str) -> tuple[str, str]:
    mapping = {
        "anima_base": ("anima", "base"),
        "anima_aesthetic": ("anima", "aesthetic"),
        "anima_turbo": ("anima", "turbo"),
        "z_image_turbo": ("z_image", "turbo"),
        "qwen_image_edit_2511": ("qwen_image_edit", "2511"),
        "generic_image": ("generic_image", "base"),
    }
    if target not in mapping:
        raise ValueError(f"不支持的 target: {target!r}")
    return mapping[target]


def _strict_image_schema(family: str) -> dict[str, Any]:
    content = (_ANIMA_CONTENT_SCHEMA if family == "anima"
               else _TEXT_CONTENT_SCHEMA)
    return {
        "type": "object", "additionalProperties": False,
        "properties": {
            "content": content,
            "negative": {"type": "string"},
        },
        "required": ["content", "negative"],
    }


def _load_strict_image_plan(payload: dict[str, Any],
                            family: str) -> ImageSemanticPlan:
    if not isinstance(payload.get("content"), dict):
        raise ValueError("content 必须是结构化对象")
    content_adapter = get_session_plan_adapter(family).content_adapter
    content = content_adapter.load(payload["content"])
    normalized = content_adapter.normalize(content)
    if family == "anima":
        ownership = normalized.validate()
        if ownership:
            raise ValueError("ANIMA Plan 所有权冲突：" + "；".join(ownership))
    elif isinstance(normalized, TextPromptPlan) and not normalized.render().strip():
        raise ValueError("结构化提示词 clauses 不能为空")
    return ImageSemanticPlan(
        content=content_adapter.dump(normalized),
        negative=str(payload.get("negative", "")).strip())


def _render_validate_strict_image(
        plan: ImageSemanticPlan, family: str, variant: str,
        bible: CharacterBible | None, book: CharacterBook | None,
        manifest: ReferenceManifest) -> tuple[str, str, ValidationReport]:
    report = ValidationReport()
    report.checks.extend(["strict_plan", f"strict_{family}"])
    candidate_issues = validate_image_candidate(plan)
    for issue in candidate_issues:
        report.add("error", "positive_negative_conflict", issue)
    if family == "anima":
        semantic = AnimaPromptPlan.from_json(plan.content).normalized()
        for issue in semantic.validate():
            report.add("error", "anima_plan_owner_conflict", issue)
        rendered = render_anima_plan(
            semantic, variant=variant, prompt_mode="natural_language",
            safety_tag="none", negative_override=plan.negative)
        positive, negative = rendered.positive, rendered.negative
    else:
        body = TextPromptPlan.from_json(plan.content).render().strip()
        if family in {"z_image", "qwen_image_edit"}:
            rendered_dict = render_special_image(
                body, family=family, variant=variant,
                negative_override=plan.negative)
        else:
            rendered_dict = render_generic(
                body, family=family, variant=variant,
                prompt_mode="natural_language", negative_override=plan.negative,
                bible=bible, book=book)
        positive = str(rendered_dict["positive"])
        negative = str(rendered_dict["negative"])
        for index, warning in enumerate(rendered_dict.get("warnings", [])):
            report.add("warning", f"renderer_warning_{index + 1}", str(warning))
    hard_report = _validate_lenient_image(
        LenientPromptOutput(prompt=positive, summary="", kind="tagged_prompt"),
        family, variant, bible, book, manifest)
    report.issues.extend(hard_report.issues)
    report.valid = report.valid and hard_report.valid
    return positive, negative, report


def _input_text(text: str, story_item: Any) -> str:
    base = str(text or "").strip()
    if not story_item:
        return base
    from ..schemas.storyboard import StoryItem

    item = StoryItem.from_json(story_item)
    story = "\n".join(part for part in (
        item.summary, item.action, item.camera) if str(part).strip())
    return "\n".join(part for part in (story, base) if part).strip()


def _character_sources(character_bible: Any, character_book: Any) -> tuple[
        CharacterBible | None, CharacterBook | None]:
    book = CharacterBook.from_json(character_book) if character_book else None
    bible = CharacterBible.from_json(character_bible) if character_bible else None
    if bible is None and book is not None:
        bible = book.first_bible()
    return bible, book


def _source_task_data(
        bible: CharacterBible | None, book: CharacterBook | None,
        manifest: ReferenceManifest) -> list[StructuredTaskData]:
    data: list[StructuredTaskData] = []
    if book is not None:
        data.append(StructuredTaskData("character_book", book.to_json()))
    elif bible is not None:
        data.append(StructuredTaskData("character_bible", bible.to_json()))
    if manifest.assets or manifest.subjects:
        data.append(StructuredTaskData("reference_manifest", manifest.to_json()))
    return data


def _validate_lenient_image(
        parsed: LenientPromptOutput, family: str, variant: str,
        bible: CharacterBible | None, book: CharacterBook | None,
        manifest: ReferenceManifest) -> ValidationReport:
    report = ValidationReport()
    report.checks.append(f"lenient_{family}")
    if parsed.kind == "protocol_garbage" or not parsed.prompt.strip():
        report.add("error", "lenient_protocol_garbage",
                   "；".join(parsed.issues) or "提示词为空")
        return report
    anchors = _identity_anchors(bible, book)
    folded = parsed.prompt.casefold()
    missing = [anchor for anchor in anchors if anchor.casefold() not in folded]
    if missing:
        report.add("error", "lenient_identity_anchor_missing",
                   "提示词缺少锁定身份锚点：" + "、".join(missing))
    if family == "anima":
        english = anima_english_issue(parsed.prompt, allowed_terms=anchors)
        if english:
            report.add("error", "anima_english_required", english)
        anima_report = validate_anima(
            parsed.prompt, _negative_for(family, variant),
            variant=variant, prompt_mode="natural_language")
        report.issues.extend(anima_report.issues)
        report.valid = report.valid and anima_report.valid
    if family == "qwen_image_edit":
        figures = [int(value) for value in re.findall(
            r"\bFigure\s+(\d+)\b", parsed.prompt, flags=re.IGNORECASE)]
        image_count = sum(1 for asset in manifest.assets
                          if asset.asset_type == "image")
        if figures and max(figures) > image_count:
            report.add("error", "qwen_figure_missing",
                       f"提示词引用 Figure {max(figures)}，但仅连接 {image_count} 张图片")
    return report


def _identity_anchors(
        bible: CharacterBible | None, book: CharacterBook | None) -> list[str]:
    bibles = list(book.characters) if book is not None else ([bible] if bible else [])
    anchors: list[str] = []
    for item in bibles:
        if item.name and item.name not in anchors:
            anchors.append(item.name)
        for trait in item.locked_traits():
            if trait.value and trait.value not in anchors:
                anchors.append(trait.value)
    return anchors


def _negative_for(family: str, variant: str) -> str:
    if family != "anima":
        return ""
    return ANIMA_BASE_NEGATIVE if variant == "base" else ANIMA_QUALITY_NEGATIVE

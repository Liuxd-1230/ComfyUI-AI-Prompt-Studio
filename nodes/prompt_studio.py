"""Persistent Image Prompt Studio with one resilient execution path."""
from __future__ import annotations

import re
from typing import Any

from ..prompting.assembly import PromptLayer, PromptSource, StructuredTaskData
from ..prompting.node_requests import assemble_prompt, report_payload, task_message
from ..prompting.operation_policies import OperationKind, operation_source
from ..prompting.output_contracts import LENIENT_PROMPT_CONTRACT
from ..prompting.studio_policies import (
    UNTRUSTED_TASK_DATA_POLICY,
    image_target_policy,
)
from ..renderers.anima import (
    ANIMA_BASE_NEGATIVE,
    ANIMA_BASE_PREFIX,
    ANIMA_QUALITY_NEGATIVE,
)
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
    build_session_fingerprints,
    message_identity,
    node_execution_result,
)
from ..services.supplements import supplement_sources as load_supplement_sources
from ..validators.anima import anima_english_issue, validate_anima
from ._helpers import require_api_key, resolve_profile_input


TARGET_OPTIONS = [
    "anima_base", "anima_aesthetic", "anima_turbo",
    "z_image_turbo", "qwen_image_edit_2511", "generic_image",
]

class APS_PromptStudio:
    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {"required": {
            "AI_PROFILE": (types.AI_PROFILE,),
            "text": ("STRING", {"default": "", "multiline": True,
                                "tooltip": "第一次写生成要求；之后只写本轮修改意见"}),
            "target": (TARGET_OPTIONS, {"default": "anima_base"}),
            "session_action": (["continue", "previous", "new"],
                               {"default": "continue"}),
        }, "optional": {
            "story_item": (types.STORY_ITEM,),
            "character_bible": (types.CHARACTER_BIBLE,),
            "character_book": (types.CHARACTER_BOOK,),
            "reference_manifest": (types.REFERENCE_MANIFEST,),
            "prompt_session": ("STRING", {"default": "", "multiline": True}),
            "message_nonce": ("STRING", {"default": "", "multiline": False}),
            "prompt_supplements": ("STRING", {"default": "", "multiline": False,
                                                 "advanced": True,
                                                 "tooltip": "高级设置：由 Markdown 补充资料选择器写入；auto=自动加载当前目标适用资料"}),
        }, "hidden": {"unique_id": "UNIQUE_ID"}}

    RETURN_TYPES = ("STRING", "STRING", types.PROMPT_SESSION, "STRING", "STRING")
    RETURN_NAMES = ("positive", "negative", "prompt_session", "validation",
                    "change_summary")
    FUNCTION = "run"
    CATEGORY = "AI Prompt Studio"
    OUTPUT_NODE = True
    DESCRIPTION = "持续维护可直接交给下游模型的图像提示词。"

    def run(self, AI_PROFILE: Any, text: str, target: str,
            session_action: str = "continue",
            story_item: Any = None, character_bible: Any = None,
            character_book: Any = None, reference_manifest: Any = None,
            prompt_session: str = "", message_nonce: str = "",
            prompt_supplements: str = "",
            unique_id: Any = None) -> Any:
        return self._run_lenient(
            AI_PROFILE, text, target, session_action, story_item,
            character_bible, character_book, reference_manifest,
            prompt_session, message_nonce, prompt_supplements, unique_id)

    def _run_lenient(
            self, AI_PROFILE: Any, text: str, target: str, session_action: str,
            story_item: Any, character_bible: Any, character_book: Any,
            reference_manifest: Any, prompt_session: str,
            message_nonce: str, prompt_supplements: str = "",
            unique_id: Any = None) -> Any:
        incoming = AIProfile.from_json(AI_PROFILE or {})
        if not incoming.profile_id:
            raise ValueError("未收到 AI_PROFILE：请先连接 AI Model Profile 节点")
        profile = resolve_profile_input(AI_PROFILE)
        api_key = require_api_key(profile)
        family, variant = _split_target(target)
        supplement_sources, supplement_hashes = load_supplement_sources(
            prompt_supplements, family=family, node_id=str(unique_id or "").strip())
        session = (PromptSession.from_json(prompt_session)
                   if prompt_session else PromptSession())
        node_id = str(unique_id or "").strip()
        journal = get_recovery_journal() if node_id else None
        if node_id:
            session, _ = session.for_node(node_id)
        if session_action == "new":
            session = PromptSession(
                target_family=family, target_variant=variant,
                node_instance_id=node_id)
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
            target_signature=f"{family}:{variant}:single",
            model_core_components=("image-studio-single", family, variant,
                                   image_target_policy(family, variant)),
            sources={"story_item": story_item, "character_bible": bible,
                     "character_book": book, "reference_manifest": manifest},
            supplement_hashes=supplement_hashes)
        context_changes = (session.fingerprints.mismatches(fingerprints)
                           if session.has_current_state else [])
        current_prompt = session.current_prompt if session.has_current_state else ""
        raw = self._generate_lenient(
            profile, api_key, family, variant, instruction, current_prompt,
            bible, book, manifest, supplement_sources)
        parsed = parse_lenient_output(raw)
        parsed = _normalize_image_output(parsed, family, variant)
        report = _validate_lenient_image(
            parsed, family, variant, bible, book, manifest)
        repair_count = 0
        if parsed.kind == "protocol_garbage" or not report.valid:
            repair_count = 1
            raw = self._repair_lenient(
                profile, api_key, family, variant, raw,
                [*parsed.issues, *[issue.message for issue in report.issues]],
                supplement_sources)
            parsed = parse_lenient_output(raw)
            parsed = _normalize_image_output(parsed, family, variant)
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
            execution_mode="single", payload_kind="freeform",
            context_changes=context_changes, node_instance_id=node_id,
            recovery_journal=journal)
        negative = _negative_for(family, variant, instruction)
        result = (parsed.prompt, negative, session.to_json_string(),
                  report.as_text(), summary)
        return node_execution_result(
            result, session.to_json_string(), parsed.prompt, summary,
            session.revision, report.as_text())

    def _generate_lenient(
            self, profile: Any, api_key: str, family: str, variant: str,
            instruction: str, current_prompt: str, bible: CharacterBible | None,
            book: CharacterBook | None, manifest: ReferenceManifest,
            supplements: list[PromptSource] | None = None) -> str:
        sources = [
            PromptSource("runtime.studio-lenient", "1.0", PromptLayer.RUNTIME,
                         UNTRUSTED_TASK_DATA_POLICY,
                         "prompt-studio"),
            PromptSource("model.image-target", "1.0", PromptLayer.MODEL_CORE,
                         image_target_policy(family, variant), "prompt-studio"),
            operation_source(
                OperationKind.REFINE if current_prompt else OperationKind.CREATE,
                scope="prompt-studio"),
        ]
        sources.extend(supplements or [])
        task_data = [StructuredTaskData("latest_instruction", instruction,
                                        "text/plain")]
        if current_prompt:
            task_data.append(StructuredTaskData(
                "current_prompt", current_prompt, "text/plain"))
        task_data.extend(_source_task_data(bible, book, manifest))
        assembly = assemble_prompt(
            sources, task_data=task_data,
            output_contract=LENIENT_PROMPT_CONTRACT)
        request = GenerateRequest(
            system=assembly.system, messages=[task_message(assembly)],
            web_search="off", reasoning=profile.reasoning,
            max_tokens=4096, timeout=profile.timeout,
            output_contract=assembly.output_contract,
            assembly_report=report_payload(assembly))
        result = Gateway().generate(profile, api_key, request)
        if result.has_error():
            raise ValueError(result.error.as_text)
        return result.text

    def _repair_lenient(
            self, profile: Any, api_key: str, family: str, variant: str,
            raw: str, issues: list[str],
            supplements: list[PromptSource] | None = None) -> str:
        assembly = assemble_prompt(
            [PromptSource("runtime.studio-lenient", "1.0", PromptLayer.RUNTIME,
                          UNTRUSTED_TASK_DATA_POLICY,
                          "prompt-studio"),
             PromptSource("model.image-target", "1.0", PromptLayer.MODEL_CORE,
                          image_target_policy(family, variant), "prompt-studio"),
             operation_source(OperationKind.FORMAT_REPAIR,
                              scope="prompt-studio"),
             *(supplements or [])],
            task_data=[StructuredTaskData("rejected_output", raw, "text/plain"),
                       StructuredTaskData("concrete_issues", issues)],
            output_contract=LENIENT_PROMPT_CONTRACT)
        request = GenerateRequest(
            system=assembly.system, messages=[task_message(assembly)],
            web_search="off", reasoning="low", max_tokens=4096,
            timeout=profile.timeout,
            output_contract=assembly.output_contract,
            assembly_report=report_payload(assembly))
        result = Gateway().generate(profile, api_key, request)
        if result.has_error():
            raise ValueError(result.error.as_text)
        return result.text

    @staticmethod
    def _freeform_result(session: PromptSession, summary: str) -> Any:
        instruction = (session.revisions[-1].user_instruction
                       if session.revisions else "")
        negative = _negative_for(
            session.target_family, session.target_variant, instruction)
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


def _input_text(text: str, story_item: Any) -> str:
    base = str(text or "").strip()
    if not story_item:
        return base
    from ..schemas.storyboard import StoryItem

    item = StoryItem.from_json(story_item)
    story = "\n".join(part for part in (
        item.title, item.text, item.location, item.camera) if str(part).strip())
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
    missing = [anchor for anchor in anchors
               if not _identity_anchor_covered(anchor, parsed.prompt)]
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
        # Generic UI labels identify the Bible entry but are not drawable identity
        # facts and must not be copied into an English image prompt verbatim.
        if (item.name and not _generic_character_label(item.name)
                and item.name not in anchors):
            anchors.append(item.name)
        for trait in item.locked_traits():
            if trait.value and trait.value not in anchors:
                anchors.append(trait.value)
    return anchors


def _generic_character_label(value: str) -> bool:
    normalized = re.sub(r"[\s_-]+", "", str(value or "")).casefold()
    return normalized in {
        "参考人物", "参考角色", "人物", "角色", "主体",
        "referencecharacter", "referenceperson", "character", "person", "subject",
    }


def _identity_anchor_covered(anchor: str, prompt: str) -> bool:
    """Require every meaningful anchor token while tolerating natural word insertion.

    This is deliberately stricter than fuzzy similarity: colors, directions, lengths,
    and distinctive nouns must still occur. It only removes punctuation/hyphen drift
    and permits harmless words such as ``hair``/``soft`` between anchor tokens.
    """
    stopwords = {"a", "an", "the", "with", "and", "of", "in", "on", "for"}
    anchor_tokens = [token for token in re.findall(r"[a-z0-9]+", anchor.casefold())
                     if token not in stopwords]
    if not anchor_tokens:
        return anchor.casefold() in prompt.casefold()
    prompt_tokens = re.findall(r"[a-z0-9]+", prompt.casefold())
    cursor = 0
    for wanted in anchor_tokens:
        try:
            cursor = prompt_tokens.index(wanted, cursor) + 1
        except ValueError:
            return False
    return True


def _normalize_image_output(
        parsed: LenientPromptOutput, family: str,
        variant: str) -> LenientPromptOutput:
    """Apply only target syntax that is deterministic and cannot change intent."""
    prompt = parsed.prompt.strip()
    if family == "anima":
        prefix = ANIMA_BASE_PREFIX if variant == "base" else "masterpiece, best quality, "
        lowered = prompt.casefold()
        if not (lowered.startswith("masterpiece,")
                or lowered.startswith("best quality,")):
            prompt = prefix + prompt
    return LenientPromptOutput(
        prompt=prompt, summary=parsed.summary, kind=parsed.kind,
        warnings=list(parsed.warnings), issues=list(parsed.issues))


def _negative_for(family: str, variant: str, instruction: str = "") -> str:
    base = (ANIMA_BASE_NEGATIVE if family == "anima" and variant == "base"
            else ANIMA_QUALITY_NEGATIVE if family == "anima" else "")
    explicit = _explicit_negative_constraints(instruction)
    return ", ".join(part for part in (base, *explicit) if part)


def _explicit_negative_constraints(instruction: str) -> list[str]:
    """Keep explicit user exclusions in the dedicated negative output."""
    results: list[str] = []
    for sentence in re.split(r"[\n。.!！；;]+", str(instruction or "")):
        match = re.match(
            r"^\s*(?:avoid|exclude|without|no|不要|避免|排除|不能有)\s*[:：]?\s*(.+?)\s*$",
            sentence, flags=re.IGNORECASE)
        if not match:
            continue
        value = match.group(1).strip(" ,，。")
        if value and value.casefold() not in {item.casefold() for item in results}:
            results.append(value)
    return results

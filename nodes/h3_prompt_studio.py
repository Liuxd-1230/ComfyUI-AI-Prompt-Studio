"""ADR 0007 MiniMax H3 Prompt Studio with lenient and strict lanes."""
from __future__ import annotations

import re
from typing import Any

from ..prompting.assembly import PromptLayer, PromptSource, StructuredTaskData
from ..prompting.node_requests import assemble_prompt, report_payload, task_message
from ..prompting.operation_policies import OperationKind, operation_source
from ..prompting.output_contracts import LENIENT_PROMPT_CONTRACT, schema_contract
from ..prompting.studio_policies import (
    UNTRUSTED_TASK_DATA_POLICY,
    h3_target_policy,
)
from ..schemas import types
from ..schemas.character import CharacterBible, CharacterBook
from ..schemas.h3 import H3_UI_MODES, H3PromptPlan
from ..schemas.profile import AIProfile
from ..schemas.prompt_plan import ValidationReport
from ..schemas.prompt_session import PromptSession
from ..schemas.references import ReferenceManifest
from ..schemas.storyboard import Storyboard
from ..services.gateway import Gateway, GenerateRequest
from ..services.h3_plan import (
    H3_SCHEMA,
    build_plan_task_data,
    parse_plan_json,
)
from ..services.h3_studio_runtime import (
    apply_changeset,
    binding_locks,
    normalize_plan,
    prepare_manifest,
    render_validate,
)
from ..services.prompt_protocol import LenientPromptOutput, parse_lenient_output
from ..services.recovery import get_recovery_journal
from ..services.prompt_session import (
    assert_session_fingerprints,
    build_session_fingerprints,
    media_fingerprint,
    message_identity,
    node_execution_result,
    request_changeset,
)
from ..services.supplements import supplement_sources as load_supplement_sources
from ..prompting.model_cores import model_core_prompt
from ..services.structured_output import raw_excerpt
from ..validators.minimax_h3 import r2v_english_issue, validate_h3
from ._helpers import require_api_key, resolve_profile_input


EXECUTION_MODES = ["lenient", "strict"]


class APS_H3PromptStudio:
    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {"required": {
            "AI_PROFILE": (types.AI_PROFILE,),
            "text": ("STRING", {"default": "", "multiline": True,
                                "tooltip": "第一次写完整导演任务；之后只写本轮修改"}),
            "mode": (H3_UI_MODES, {
                "default": "T2VA",
                "tooltip": "T2VA 文生视频；I2VA 首帧；FL2VA 首尾帧；L2VA 尾帧；Ref2VA 多模态参考",
            }),
            "duration": ("FLOAT", {"default": 10.0, "min": 4.0, "max": 15.0}),
            "execution_mode": (EXECUTION_MODES, {
                "default": "lenient",
                "tooltip": "lenient 宽松：直接维护成品提示词；strict 严格：结构化 Plan + ChangeSet 校验",
            }),
            "session_action": (["continue", "previous", "new"],
                               {"default": "continue"}),
        }, "optional": {
            "storyboard": (types.STORYBOARD,),
            "character_bible": (types.CHARACTER_BIBLE,),
            "character_book": (types.CHARACTER_BOOK,),
            "reference_manifest": (types.REFERENCE_MANIFEST,),
            "images": ("IMAGE",),
            "video_1": ("VIDEO",), "video_2": ("VIDEO",),
            "video_3": ("VIDEO",), "audio_1": ("AUDIO",),
            "audio_2": ("AUDIO",), "audio_3": ("AUDIO",),
            "prompt_session": ("STRING", {"default": "", "multiline": True}),
            "message_nonce": ("STRING", {"default": "", "multiline": False}),
            "prompt_supplements": ("STRING", {"default": "", "multiline": False,
                                                 "advanced": True,
                                                 "tooltip": "高级设置：由 Markdown 补充资料选择器写入；auto=自动加载当前目标适用资料"}),
        }, "hidden": {"unique_id": "UNIQUE_ID"}}

    RETURN_TYPES = ("STRING", types.PROMPT_SESSION, types.REFERENCE_MANIFEST,
                    "STRING", "STRING")
    RETURN_NAMES = ("prompt", "prompt_session", "REFERENCE_MANIFEST",
                    "validation", "change_summary")
    FUNCTION = "run"
    CATEGORY = "AI Prompt Studio"
    OUTPUT_NODE = True
    DESCRIPTION = "默认宽松、可选严格的持续 MiniMax H3 提示词工作台。"

    def run(self, AI_PROFILE: Any, text: str, mode: str, duration: float,
            execution_mode: str = "lenient", session_action: str = "continue",
            storyboard: Any = None, character_bible: Any = None,
            character_book: Any = None, reference_manifest: Any = None,
            images: Any = None, video_1: Any = None, video_2: Any = None,
            video_3: Any = None, audio_1: Any = None, audio_2: Any = None,
            audio_3: Any = None, prompt_session: str = "",
            message_nonce: str = "", prompt_supplements: str = "",
            unique_id: Any = None) -> Any:
        mode = _normalize_mode(mode)
        if execution_mode not in EXECUTION_MODES:
            raise ValueError("execution_mode 必须是 lenient 或 strict")
        if not 4.0 <= float(duration) <= 15.0:
            raise ValueError("MiniMax H3 目标时长必须在 4–15 秒之间")
        incoming = AIProfile.from_json(AI_PROFILE or {})
        if not incoming.profile_id:
            raise ValueError("未收到 AI_PROFILE：请先连接 AI Model Profile 节点")
        profile = resolve_profile_input(AI_PROFILE)
        api_key = require_api_key(profile)
        supplement_sources, supplement_hashes = load_supplement_sources(
            prompt_supplements, family="minimax_h3", node_id=str(unique_id or "").strip())
        manifest, image_count = prepare_manifest(
            reference_manifest, images, (video_1, video_2, video_3),
            (audio_1, audio_2, audio_3))
        bible = CharacterBible.from_json(character_bible) if character_bible else None
        book = CharacterBook.from_json(character_book) if character_book else None
        if bible is None and book is not None:
            bible = book.first_bible()
        board = Storyboard.from_json(storyboard) if storyboard else None
        source_bibles = _source_bibles(bible, book, board, bool(character_bible))
        sources = {"storyboard": board, "character_bible": bible,
                   "character_book": book, "reference_manifest": manifest,
                   "images": media_fingerprint(images),
                   "video_1": media_fingerprint(video_1),
                   "video_2": media_fingerprint(video_2),
                   "video_3": media_fingerprint(video_3),
                   "audio_1": media_fingerprint(audio_1),
                   "audio_2": media_fingerprint(audio_2),
                   "audio_3": media_fingerprint(audio_3)}
        fingerprints = build_session_fingerprints(
            target_signature=f"minimax_h3:{mode}:{execution_mode}",
            model_core_components=("h3-studio", execution_mode,
                                   model_core_prompt("minimax_h3"), validate_h3),
            sources=sources,
            supplement_hashes=supplement_hashes,
            )
        if execution_mode == "lenient":
            return self._run_lenient(
                profile, api_key, text, mode, duration, session_action,
                board, bible, book, source_bibles, manifest, image_count, prompt_session,
                message_nonce, fingerprints, supplement_sources, unique_id)
        return self._run_strict(
            profile, api_key, text, mode, duration, session_action,
            board, bible, book, source_bibles, manifest, image_count, prompt_session,
            message_nonce, fingerprints, supplement_sources, unique_id)

    def _run_lenient(
            self, profile: AIProfile, api_key: str, text: str, mode: str,
            duration: float, session_action: str, storyboard: Storyboard | None,
            bible: CharacterBible | None, book: CharacterBook | None,
            source_bibles: list[CharacterBible], manifest: ReferenceManifest,
            image_count: int, prompt_session: str,
            message_nonce: str, fingerprints: Any,
            supplements: list[PromptSource] | None = None,
            unique_id: Any = None) -> Any:
        session = PromptSession.from_json(prompt_session) if prompt_session else PromptSession()
        node_id = str(unique_id or "").strip()
        journal = get_recovery_journal() if node_id else None
        if node_id:
            session, _ = session.for_node(node_id)
        if session_action == "new" or (
                session.has_current_state and session.execution_mode != "lenient"):
            session = PromptSession(target_family="minimax_h3", target_variant=mode,
                                    execution_mode="lenient",
                                    node_instance_id=node_id)
        if session_action == "previous":
            if not session.revert_previous(
                    node_instance_id=node_id, recovery_journal=journal):
                raise ValueError("当前 H3 会话尚无可恢复的成功版本")
            return self._result(session, manifest, "已恢复上一版 H3 提示词。")
        instruction = str(text or "").strip()
        if not instruction:
            if session.has_current_state:
                return self._result(session, manifest, "没有新的消息；未调用模型。")
            raise ValueError("text 不能为空")
        message_id = message_identity(message_nonce, instruction)
        if session.has_current_state and session.has_processed_message(message_id):
            return self._result(session, manifest, "没有新的消息；未调用模型。")
        current_prompt = session.current_prompt if session.has_current_state else ""
        context_changes = (session.fingerprints.mismatches(fingerprints)
                           if session.has_current_state else [])
        raw = self._generate_lenient(
            profile, api_key, instruction, current_prompt, mode, duration,
            storyboard, bible, book, manifest, supplements)
        parsed = parse_lenient_output(raw)
        report = _validate_lenient_h3(
            parsed, mode, duration, manifest, image_count, source_bibles,
            instruction)
        repair_count = 0
        if parsed.kind == "protocol_garbage" or not report.valid:
            repair_count = 1
            raw = self._repair_lenient(
                profile, api_key, raw,
                [*parsed.issues, *[item.message for item in report.issues]],
                mode, duration, supplements)
            parsed = parse_lenient_output(raw)
            report = _validate_lenient_h3(
                parsed, mode, duration, manifest, image_count, source_bibles,
                instruction)
        if parsed.kind == "protocol_garbage" or not report.valid:
            detail = report.as_text() if report.issues else "；".join(parsed.issues)
            raise ValueError(
                "H3 宽松提示词修复一次后仍不可用；上一版保持不变：\n" +
                detail + "\n模型原始输出（截断）：" + raw_excerpt(raw))
        for warning in parsed.warnings:
            report.add("warning", "lenient_untagged_prompt", warning)
        for change in context_changes:
            report.add("warning", "lenient_context_changed",
                       f"上下文已变化但宽松模式继续执行：{change}")
        summary = parsed.summary or (
            "已更新 H3 提示词。" if session.has_current_state else "已创建 H3 提示词。")
        session.target_family, session.target_variant = "minimax_h3", mode
        session.commit(
            {}, parsed.prompt, report, instruction, summary,
            expected_revision=session.revision, message_id=message_id,
            fingerprints=fingerprints, execution_mode="lenient",
            payload_kind="freeform", repair_count=repair_count,
            context_changes=context_changes, node_instance_id=node_id,
            recovery_journal=journal)
        return self._result(session, manifest, summary)

    def _run_strict(
            self, profile: AIProfile, api_key: str, text: str, mode: str,
            duration: float, session_action: str, storyboard: Storyboard | None,
            bible: CharacterBible | None, book: CharacterBook | None,
            source_bibles: list[CharacterBible], manifest: ReferenceManifest,
            image_count: int, prompt_session: str,
            message_nonce: str, fingerprints: Any,
            supplements: list[PromptSource] | None = None,
            unique_id: Any = None) -> Any:
        stable = PromptSession.from_json(prompt_session) if prompt_session else PromptSession()
        node_id = str(unique_id or "").strip()
        journal = get_recovery_journal() if node_id else None
        if node_id:
            stable, _ = stable.for_node(node_id)
        starts_new = session_action == "new" or (
            stable.has_current_state and stable.execution_mode != "strict")
        session = (PromptSession(target_family="minimax_h3", target_variant=mode,
                                 execution_mode="strict",
                                 node_instance_id=node_id)
                   if starts_new else stable)
        if session_action == "previous" and not starts_new:
            assert_session_fingerprints(session, fingerprints)
            if not session.revert_previous(
                    node_instance_id=node_id, recovery_journal=journal):
                raise ValueError("当前 H3 会话尚无可恢复的成功版本")
            return self._result(session, manifest, "已恢复上一版 H3 方案。")
        instruction = str(text or "").strip()
        if session.has_current_state:
            assert_session_fingerprints(session, fingerprints)
        if not instruction:
            if session.has_current_state:
                return self._result(session, manifest, "没有新的消息；未调用模型。")
            raise ValueError("text 不能为空")
        message_id = message_identity(message_nonce, instruction)
        if session.has_current_state and session.has_processed_message(message_id):
            return self._result(session, manifest, "没有新的消息；未调用模型。")
        if not session.has_current_plan:
            plan, repair_count = self._create_strict(
                profile, api_key, instruction, mode, duration, storyboard,
                bible, book, manifest, image_count, supplements)
            summary, changeset = "已创建第一版严格 H3 方案。", None
        else:
            changeset = request_changeset(
                Gateway(), profile, api_key, session, instruction,
                {"mode": mode, "duration_seconds": duration,
                 "image_count": image_count})
            plan = apply_changeset(
                session, changeset, mode=mode, duration=duration,
                manifest=manifest, image_count=image_count)
            repair_count, summary = 0, changeset.summary
        plan = normalize_plan(plan, manifest, image_count, mode, duration)
        rendered, report = render_validate(
            plan, manifest, image_count, mode, duration)
        if mode == "Ref2VA" and r2v_english_issue(rendered):
            report.add("error", "h3_ref2va_english",
                       "Ref2VA 语义描述必须使用英文；对白/歌词/画面文字除外")
        _append_identity_anchor_errors(report, rendered, source_bibles)
        camera_issue = _camera_motion_intent_issue(instruction, rendered)
        if camera_issue:
            report.add("error", "h3_camera_motion_mismatch", camera_issue)
        shot_count_issue = _shot_count_intent_issue(instruction, rendered)
        if shot_count_issue:
            report.add("error", "h3_shot_count_mismatch", shot_count_issue)
        if not report.valid:
            raise ValueError("H3 严格模式校验未通过；上一版保持不变：\n" + report.as_text())
        bundle = {"h3_plan": plan.to_json(),
                  "reference_manifest": manifest.to_json()}
        session.target_family, session.target_variant = "minimax_h3", mode
        session.commit(
            bundle, rendered, report, instruction, summary,
            expected_revision=session.revision, message_id=message_id,
            fingerprints=fingerprints, execution_mode="strict",
            payload_kind="structured", repair_count=repair_count,
            requested_paths=([item.path for item in changeset.requested_changes]
                             if changeset else []),
            dependent_paths=([item.path for item in changeset.dependent_changes]
                             if changeset else []),
            invalidated_paths=([item.path for item in changeset.invalidated_facts]
                               if changeset else []),
            renderer_signature=fingerprints.model_core_hash,
            locked_constraints=binding_locks(plan), node_instance_id=node_id,
            recovery_journal=journal)
        return self._result(session, manifest, summary)

    def _generate_lenient(
            self, profile: AIProfile, api_key: str, instruction: str,
            current_prompt: str, mode: str, duration: float,
            storyboard: Storyboard | None, bible: CharacterBible | None,
            book: CharacterBook | None, manifest: ReferenceManifest,
            supplements: list[PromptSource] | None = None) -> str:

        sources = [
            PromptSource("runtime.studio-lenient", "1.0", PromptLayer.RUNTIME,
                         UNTRUSTED_TASK_DATA_POLICY,
                         "h3-studio"),
            PromptSource("model.minimax-h3", "1.0", PromptLayer.MODEL_CORE,
                         h3_target_policy(mode, duration), "h3-studio"),
            operation_source(
                OperationKind.REFINE if current_prompt else OperationKind.CREATE,
                scope="h3-studio"),
        ]
        sources.extend(supplements or [])
        task_data = [StructuredTaskData("latest_instruction", instruction, "text/plain")]
        if current_prompt:
            task_data.append(StructuredTaskData("current_prompt", current_prompt,
                                                "text/plain"))
        task_data.extend(_h3_task_sources(storyboard, bible, book, manifest))
        assembly = assemble_prompt(
            sources, task_data=task_data,
            output_contract=LENIENT_PROMPT_CONTRACT)
        req = GenerateRequest(
            system=assembly.system, messages=[task_message(assembly)], web_search="off",
            reasoning=profile.reasoning, max_tokens=8192, timeout=profile.timeout,
            output_contract=assembly.output_contract,
            assembly_report=report_payload(assembly))
        result = Gateway().generate(profile, api_key, req)
        if result.has_error():
            raise ValueError(result.error.as_text)
        return result.text

    def _repair_lenient(self, profile: AIProfile, api_key: str, raw: str,
                        issues: list[str], mode: str, duration: float,
                        supplements: list[PromptSource] | None = None) -> str:
        assembly = assemble_prompt(
            [PromptSource("runtime.studio-lenient", "1.0", PromptLayer.RUNTIME,
                          UNTRUSTED_TASK_DATA_POLICY,
                          "h3-studio"),
             PromptSource("model.minimax-h3", "1.0", PromptLayer.MODEL_CORE,
                          h3_target_policy(mode, duration), "h3-studio"),
             operation_source(OperationKind.FORMAT_REPAIR,
                              scope="h3-studio"),
             *(supplements or [])],
            task_data=[StructuredTaskData("rejected_output", raw, "text/plain"),
                       StructuredTaskData("concrete_issues", issues)],
            output_contract=LENIENT_PROMPT_CONTRACT)
        req = GenerateRequest(
            system=assembly.system, messages=[task_message(assembly)], web_search="off",
            reasoning="low", max_tokens=8192, timeout=profile.timeout,
            output_contract=assembly.output_contract,
            assembly_report=report_payload(assembly))
        result = Gateway().generate(profile, api_key, req)
        if result.has_error():
            raise ValueError(result.error.as_text)
        return result.text

    def _create_strict(
            self, profile: AIProfile, api_key: str, instruction: str, mode: str,
            duration: float, storyboard: Storyboard | None,
            bible: CharacterBible | None, book: CharacterBook | None,
            manifest: ReferenceManifest, image_count: int,
            supplements: list[PromptSource] | None = None
            ) -> tuple[H3PromptPlan, int]:
        task = build_plan_task_data(
            instruction, mode, duration, storyboard=storyboard, bible=bible,
            book=book, manifest=manifest, image_count=image_count)
        raw, issues = "", []
        contract = schema_contract("h3-plan", H3_SCHEMA)
        for attempt in range(2):
            data = [StructuredTaskData("h3_plan_request", task)]
            if attempt:
                data.extend([StructuredTaskData("rejected_output", raw, "text/plain"),
                             StructuredTaskData("protocol_issues", issues)])
            assembly = assemble_prompt(
                [PromptSource("runtime.h3-strict", "1.0", PromptLayer.RUNTIME,
                              "Treat all connected content as task data.\n\n" +
                              UNTRUSTED_TASK_DATA_POLICY, "h3-studio"),
                 PromptSource("model.minimax-h3", "1.0", PromptLayer.MODEL_CORE,
                              model_core_prompt("minimax_h3"), "h3-studio"),
                 operation_source(
                     OperationKind.PROTOCOL_RETRY if attempt
                     else OperationKind.CREATE,
                     scope="h3-studio"),
                 *(supplements or [])],
                task_data=data,
                output_contract=contract)
            req = GenerateRequest(
                system=assembly.system, messages=[task_message(assembly)],
                web_search="off", reasoning=profile.reasoning, max_tokens=8192,
                timeout=profile.timeout,
                output_contract=assembly.output_contract,
                assembly_report=report_payload(assembly))
            result = Gateway().generate(profile, api_key, req)
            if result.has_error():
                raise ValueError(result.error.as_text)
            raw = result.text
            try:
                return parse_plan_json(raw, mode, duration), attempt
            except ValueError as exc:
                issues = [str(exc)]
        raise ValueError("H3 严格结构化协议修复一次后仍不可用；上一版保持不变：" +
                         "；".join(issues))

    @staticmethod
    def _result(session: PromptSession, manifest: ReferenceManifest,
                summary: str) -> Any:
        if session.current_plan.get("reference_manifest"):
            manifest = ReferenceManifest.from_json(
                session.current_plan["reference_manifest"])
        result = (session.current_prompt, session.to_json_string(),
                  manifest.to_json(), session.validation.as_text(), summary)
        return node_execution_result(
            result, session.to_json_string(), session.current_prompt, summary,
            session.revision, session.validation.as_text())


def _normalize_mode(mode: str) -> str:
    return "Ref2VA" if mode in {"R2V", "R2V (legacy)"} else mode


def _h3_task_sources(
        storyboard: Storyboard | None, bible: CharacterBible | None,
        book: CharacterBook | None,
        manifest: ReferenceManifest) -> list[StructuredTaskData]:
    result: list[StructuredTaskData] = []
    if storyboard is not None:
        result.append(StructuredTaskData("storyboard", storyboard.to_json()))
    if book is not None:
        result.append(StructuredTaskData("character_book", book.to_json()))
    elif bible is not None:
        result.append(StructuredTaskData("character_bible", bible.to_json()))
    if manifest.assets or manifest.subjects:
        result.append(StructuredTaskData("reference_manifest", manifest.to_json()))
    return result


def _validate_lenient_h3(
        parsed: LenientPromptOutput, mode: str, duration: float,
        manifest: ReferenceManifest, image_count: int,
        source_bibles: list[CharacterBible], instruction: str) -> ValidationReport:
    if parsed.kind == "protocol_garbage" or not parsed.prompt.strip():
        report = ValidationReport()
        report.add("error", "lenient_protocol_garbage",
                   "；".join(parsed.issues) or "提示词为空")
        return report
    report = validate_h3(parsed.prompt, mode, duration=duration, manifest=manifest)
    required = {"T2VA": 0, "I2VA": 1, "FL2VA": 2, "L2VA": 1}.get(mode)
    if required is not None and image_count != required:
        report.add("error", "h3_asset_mode",
                   f"{mode} 需要 {required} 张参考图，实际 {image_count}")
    if mode == "Ref2VA" and r2v_english_issue(parsed.prompt):
        report.add("error", "h3_ref2va_english",
                   "Ref2VA 语义描述必须使用英文；对白/歌词/画面文字除外")
    _append_identity_anchor_errors(report, parsed.prompt, source_bibles)
    camera_issue = _camera_motion_intent_issue(instruction, parsed.prompt)
    if camera_issue:
        report.add("error", "h3_camera_motion_mismatch", camera_issue)
    shot_count_issue = _shot_count_intent_issue(instruction, parsed.prompt)
    if shot_count_issue:
        report.add("error", "h3_shot_count_mismatch", shot_count_issue)
    return report


def _camera_motion_intent_issue(instruction: str, prompt: str) -> str:
    """Reject the common pan/truck mistranslation when intent is explicit."""
    requested = str(instruction or "")
    rendered = str(prompt or "").lower()
    if "横移" in requested and re.search(r"\bpan(?:s|ning|ned)?\b", rendered):
        return "用户要求横移（truck/sideways translation），输出却使用 pan（固定机位摇摄）"
    if any(token in requested for token in ("摇摄", "摇镜")) and re.search(
            r"\btruck(?:s|ing|ed)?\b", rendered):
        return "用户要求摇摄（pan/rotation），输出却使用 truck（整机横移）"
    return ""


def _shot_count_intent_issue(instruction: str, prompt: str) -> str:
    """Enforce an explicit one-shot request without guessing other shot counts."""
    requested = str(instruction or "").lower()
    single_shot = any(token in requested for token in (
        "单镜头", "一镜到底", "single shot", "one continuous shot", "one-shot"))
    if single_shot and re.search(r"\[shot\s+[2-9]\d*\]", str(prompt or ""), re.I):
        return "用户明确要求单镜头/一镜到底，输出不得包含 [Shot 2] 或后续镜头"
    return ""


def _source_bibles(
        bible: CharacterBible | None, book: CharacterBook | None,
        storyboard: Storyboard | None, explicit_bible: bool) -> list[CharacterBible]:
    if explicit_bible and bible is not None:
        return [bible]
    if book is None:
        return [bible] if bible is not None else []
    if storyboard is None:
        return list(book.characters)
    used = set(storyboard.characters)
    for scene in storyboard.scenes:
        used.update(scene.characters)
        for shot in scene.shots:
            used.update(shot.characters)
    return [item for item in book.characters if item.character_id in used]


def _append_identity_anchor_errors(
        report: ValidationReport, prompt: str,
        bibles: list[CharacterBible]) -> None:
    folded = prompt.casefold()
    missing: list[str] = []
    for bible in bibles:
        anchors = [bible.name, *[item.value for item in bible.locked_traits()]]
        missing.extend(anchor for anchor in anchors
                       if anchor and anchor.casefold() not in folded)
    if missing:
        report.add("error", "h3_identity_anchor_missing",
                   "H3 提示词缺少锁定身份锚点：" + "、".join(dict.fromkeys(missing)))

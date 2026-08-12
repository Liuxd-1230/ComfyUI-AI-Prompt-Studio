"""Deterministic media, transaction, render, and validation seams for H3 Studio."""
from __future__ import annotations

import copy
import json
from typing import Any

from ..domain.impact_analysis import analyze_h3_impacts
from ..domain.plan_adapters import get_plan_adapter
from ..domain.transactions import SemanticTransaction
from ..renderers.minimax_h3 import render_h3
from ..schemas.changeset import ChangeSet, SemanticChange
from ..schemas.h3 import H3PromptPlan
from ..schemas.prompt_session import PromptSession
from ..schemas.references import AssetRef, ReferenceManifest
from ..services.h3_plan import (
    map_image_assets,
    normalize_media_labels,
    sync_manifest_assets,
)
from ..validators.minimax_h3 import validate_h3


MODE_IMAGE_REQUIREMENTS = {"T2VA": 0, "I2VA": 1, "FL2VA": 2, "L2VA": 1}


def count_images(images: Any) -> int:
    if images is None:
        return 0
    if hasattr(images, "shape"):
        shape = images.shape
        return int(shape[0]) if len(shape) >= 3 else 1
    return len(images) if isinstance(images, (list, tuple)) else 1


def prepare_manifest(reference_manifest: Any, images: Any,
                     videos: tuple[Any, ...], audios: tuple[Any, ...]
                     ) -> tuple[ReferenceManifest, int]:
    manifest = (ReferenceManifest.from_json(reference_manifest)
                if reference_manifest else ReferenceManifest())
    image_count = count_images(images)
    _register_images(manifest, image_count)
    _register_media(manifest, "video", videos)
    _register_media(manifest, "audio", audios)
    return manifest, image_count


def normalize_plan(plan: H3PromptPlan, manifest: ReferenceManifest,
                   image_count: int, mode: str, duration: float) -> H3PromptPlan:
    previous_indices = [shot.index for shot in plan.shots]
    plan.duration_seconds = float(duration)
    if plan.shots:
        plan.shots[0].start_time = None
    sync_manifest_assets(plan, manifest)
    plan.warnings = list(dict.fromkeys(
        [*plan.warnings, *map_image_assets(plan, image_count, mode)]))
    normalize_media_labels(plan)
    normalized = get_plan_adapter("minimax_h3").normalize(plan)
    expected_indices = list(range(1, len(normalized.shots) + 1))
    if previous_indices and previous_indices != expected_indices:
        warning = "镜头列表发生插入/删除或编号不连续，已按当前顺序重新编号"
        if warning not in normalized.warnings:
            normalized.warnings.append(warning)
    return normalized


def render_validate(plan: H3PromptPlan, manifest: ReferenceManifest,
                    image_count: int, mode: str, duration: float
                    ) -> tuple[str, Any]:
    rendered = render_h3(plan)
    report = validate_h3(
        rendered, mode, duration=duration, manifest=manifest, plan=plan)
    required = MODE_IMAGE_REQUIREMENTS.get(mode)
    if required is not None and image_count != required:
        report.add("error", "h3_asset_mode",
                   f"{mode} 需要 {required} 张参考图，实际 {image_count}")
    return rendered, report


def apply_changeset(session: PromptSession, changeset: ChangeSet, *,
                    mode: str, duration: float, manifest: ReferenceManifest,
                    image_count: int) -> H3PromptPlan:
    adapter = get_plan_adapter("minimax_h3")
    current = adapter.load(session.current_plan.get("h3_plan", {}))
    duration_change = next((item for item in changeset.all_changes()
                            if item.path == "duration_seconds"), None)
    if float(current.duration_seconds) != float(duration):
        if duration_change is None:
            changeset.intent_scope.append("duration_seconds")
            changeset.approved_requested_paths.append("duration_seconds")
            changeset.requested_changes.append(SemanticChange(
                path="duration_seconds", operation="set", value=float(duration),
                reason="H3 Studio duration 控件是本轮权威输入"))
        elif (not isinstance(duration_change.value, (int, float))
              or float(duration_change.value) != float(duration)):
            raise ValueError("ChangeSet duration_seconds 与节点 duration 输入冲突")
    locked = ["mode", "storyboard_id", "plan_id", "created_at",
              "validation", "raw"]
    locked.extend(resolve_locked_paths(session))

    def runtime_normalizer(candidate: H3PromptPlan) -> H3PromptPlan:
        return normalize_plan(candidate, manifest, image_count, mode, duration)

    payload = adapter.dump(current)
    allowed = [key for key in payload if key not in {
        "schema_version", "plan_id", "created_at", "validation", "raw",
        "warnings", "storyboard_id"}]
    result = SemanticTransaction(adapter).execute(
        current, changeset, current_revision=session.revision,
        impact_analyzer=analyze_h3_impacts, allowed_roots=allowed,
        locked_paths=locked,
        broad_only_roots=("shots", "speakers", "subjects", "assets", "retention"),
        normalization_paths=("duration_seconds", "shots", "speakers", "assets",
                             "subjects", "retention", "warnings"),
        normalizer=runtime_normalizer,
        allow_broad=changeset.change_category == "broad_rewrite",
        semantic_check=lambda candidate: stable_lock_issues(
            candidate, session.locked_constraints))
    changeset.dependent_changes = copy.deepcopy(result.changeset.dependent_changes)
    changeset.invalidated_facts = copy.deepcopy(result.changeset.invalidated_facts)
    return result.plan


def binding_locks(plan: H3PromptPlan) -> list[str]:
    locks: list[str] = []
    for speaker in plan.speakers:
        locks.append("fact:" + json.dumps({
            "kind": "h3_speaker", "speaker_id": speaker.speaker_id,
            "character_id": speaker.character_id,
        }, ensure_ascii=False, sort_keys=True))
    for subject in plan.subjects:
        locks.append("fact:" + json.dumps({
            "kind": "h3_subject", "label": subject.label,
            "source_assets": list(subject.source_assets),
        }, ensure_ascii=False, sort_keys=True))
    for asset in plan.assets:
        locks.append("fact:" + json.dumps({
            "kind": "h3_asset", "label": asset.label, "source": asset.source,
        }, ensure_ascii=False, sort_keys=True))
    return locks


def resolve_locked_paths(session: PromptSession) -> list[str]:
    plan = H3PromptPlan.from_json(session.current_plan.get("h3_plan", {}))
    paths: list[str] = []
    for raw in session.locked_constraints:
        value = str(raw).strip().strip("/")
        if not value.startswith("fact:"):
            paths.append(value[len("h3_plan/"):] if value.startswith("h3_plan/") else value)
            continue
        try:
            fact = json.loads(value[len("fact:"):])
        except ValueError:
            continue
        if fact.get("kind") == "h3_speaker":
            for index, speaker in enumerate(plan.speakers):
                if speaker.speaker_id == fact.get("speaker_id"):
                    paths.append(f"speakers/{index}/speaker_id")
                    if fact.get("character_id"):
                        paths.append(f"speakers/{index}/character_id")
        elif fact.get("kind") == "h3_subject":
            for index, subject in enumerate(plan.subjects):
                if subject.label == fact.get("label"):
                    paths.extend([f"subjects/{index}/label",
                                  f"subjects/{index}/source_assets"])
        elif fact.get("kind") == "h3_asset":
            for index, asset in enumerate(plan.assets):
                if asset.label == fact.get("label"):
                    paths.extend([f"assets/{index}/label", f"assets/{index}/source"])
    return list(dict.fromkeys(paths))


def stable_lock_issues(plan: H3PromptPlan, constraints: list[str]) -> list[str]:
    speakers = {item.speaker_id: item for item in plan.speakers}
    subjects = {item.label: item for item in plan.subjects}
    assets = {item.label: item for item in plan.assets}
    issues: list[str] = []
    for raw in constraints:
        if not str(raw).startswith("fact:"):
            continue
        try:
            fact = json.loads(str(raw)[len("fact:"):])
        except ValueError:
            issues.append("损坏的 H3 稳定事实锁")
            continue
        kind = fact.get("kind")
        if kind == "h3_speaker":
            speaker = speakers.get(str(fact.get("speaker_id", "")))
            if speaker is None or speaker.character_id != fact.get("character_id", ""):
                issues.append(f"锁定 speaker 身份已改变: {fact.get('speaker_id', '')}")
        elif kind == "h3_subject":
            subject = subjects.get(str(fact.get("label", "")))
            if subject is None or subject.source_assets != fact.get("source_assets", []):
                issues.append(f"锁定 subject 绑定已改变: {fact.get('label', '')}")
        elif kind == "h3_asset":
            asset = assets.get(str(fact.get("label", "")))
            if asset is None or asset.source != fact.get("source", ""):
                issues.append(f"锁定 asset 绑定已改变: {fact.get('label', '')}")
    return issues


def _register_images(manifest: ReferenceManifest, count: int) -> None:
    existing = {asset.asset_id for asset in manifest.assets}
    for index in range(1, count + 1):
        if f"image_{index}" not in existing:
            manifest.add_asset(AssetRef(
                asset_id=f"image_{index}", asset_type="image", data_ref="images",
                source="APS_H3PromptStudio", h3_labels=[f"Picture {index}"],
                note=f"connected picture reference {index}"))


def _register_media(manifest: ReferenceManifest, kind: str,
                    values: tuple[Any, ...]) -> None:
    existing = {asset.asset_id for asset in manifest.assets}
    for index, value in enumerate(values, start=1):
        if value is None or f"{kind}_{index}" in existing:
            continue
        duration = _media_duration(value)
        manifest.add_asset(AssetRef(
            asset_id=f"{kind}_{index}", asset_type=kind,
            data_ref=f"{kind}_{index}", source="APS_H3PromptStudio",
            h3_labels=[f"{kind.title()} {index}"],
            note=f"connected {kind} reference {index}",
            time_start=0.0 if duration is not None else None,
            time_end=duration))


def _media_duration(value: Any) -> float | None:
    if isinstance(value, dict):
        waveform, sample_rate = value.get("waveform"), value.get("sample_rate")
        shape = getattr(waveform, "shape", ())
        if shape and sample_rate:
            return float(shape[-1]) / float(sample_rate)
    try:
        frames, rate = value.get_frame_count(), value.get_frame_rate()
        if frames is not None and rate:
            return float(frames) / float(rate)
    except (AttributeError, TypeError, ValueError):
        pass
    return None

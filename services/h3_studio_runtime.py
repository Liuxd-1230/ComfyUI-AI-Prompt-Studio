"""Deterministic media, transaction, render, and validation seams for H3 Studio."""
from __future__ import annotations

from typing import Any

from ..domain.plan_adapters import get_plan_adapter
from ..renderers.minimax_h3 import render_h3
from ..schemas.character import CharacterBible
from ..schemas.h3 import H3PromptPlan
from ..schemas.references import AssetRef, ReferenceManifest
from ..services.h3_plan import (
    map_image_assets,
    normalize_media_labels,
    normalize_ref2va_summary,
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
                   image_count: int, mode: str, duration: float,
                   source_bibles: list[CharacterBible] | None = None) -> H3PromptPlan:
    previous_indices = [shot.index for shot in plan.shots]
    plan.duration_seconds = float(duration)
    if plan.shots:
        plan.shots[0].start_time = None
    sync_manifest_assets(plan, manifest)
    plan.warnings = list(dict.fromkeys(
        [*plan.warnings, *map_image_assets(plan, image_count, mode)]))
    normalize_media_labels(plan)
    normalize_ref2va_summary(plan)
    _inject_locked_identity(plan, source_bibles or [])
    normalized = get_plan_adapter("minimax_h3").normalize(plan)
    expected_indices = list(range(1, len(normalized.shots) + 1))
    if previous_indices and previous_indices != expected_indices:
        warning = "镜头列表发生插入/删除或编号不连续，已按当前顺序重新编号"
        if warning not in normalized.warnings:
            normalized.warnings.append(warning)
    return normalized


def _inject_locked_identity(
        plan: H3PromptPlan, source_bibles: list[CharacterBible]) -> None:
    """Copy authoritative locked drawable traits into a character's first shot."""
    if not plan.shots:
        return
    shot = plan.shots[0]
    existing = " ".join(shot.description).casefold()
    for bible in source_bibles:
        traits = [trait.value.strip() for trait in bible.locked_traits()
                  if trait.value.strip() and trait.value.casefold() not in existing]
        if not traits:
            continue
        subject = bible.name.strip() or bible.character_id.strip() or "The character"
        sentence = f"{subject}'s locked visual identity: {', '.join(traits)}."
        shot.description.insert(0, sentence)
        existing += " " + sentence.casefold()


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


def _register_images(manifest: ReferenceManifest, count: int) -> None:
    existing_images = [asset for asset in manifest.assets
                       if asset.asset_type == "image"]
    for index in range(1, count + 1):
        if index <= len(existing_images):
            asset = existing_images[index - 1]
            label = f"Picture {index}"
            if label not in asset.h3_labels:
                asset.h3_labels.append(label)
            continue
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

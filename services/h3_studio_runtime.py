"""Deterministic media registration for the H3 Studio reference manifest."""
from __future__ import annotations

from typing import Any

from ..schemas.references import AssetRef, ReferenceManifest


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
            note=(f"unanalysed connected picture reference {index}; "
                  "raw pixels are unavailable to the prompt-writing model")))


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

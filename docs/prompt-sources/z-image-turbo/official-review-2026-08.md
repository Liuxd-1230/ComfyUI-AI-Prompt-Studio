# Z-Image Turbo Official Review — 2026-08

Primary source: [Tongyi-MAI Z-Image-Turbo model card](https://huggingface.co/Tongyi-MAI/Z-Image-Turbo).

## Verified Facts

- Turbo is the distilled text-to-image variant and targets 8 NFEs without CFG.
- It emphasizes photorealism, Chinese/English text rendering, and instruction adherence.
- The official Diffusers example uses a concrete natural description covering subject, clothing/material detail, props, lighting, setting, and visible text. It uses `num_inference_steps=9` (eight DiT forwards) and `guidance_scale=0.0`.
- The official table distinguishes Turbo generation from the separate Edit model; negative prompting is a foundation-model capability, not a Turbo recommendation.

## Local Diff

- `unchanged`: `render_special_image` emits steps 9 and CFG 0, no independent negative prompt.
- `unchanged`: the former local guidance requested coherent, visible natural-language details rather than tag soup; this rule now belongs to `prompting/model_cores.py`.
- `new`: official evidence explicitly establishes bilingual visible-text strength; local guidance does not yet give visible-text quoting/preservation its own semantic field.
- `unsupported local assumption`: the warning that prompts under 80 characters are inherently weak is not stated by the official source. Length should be judged by missing semantic content, not a character threshold.

The unsupported heuristic remains historical research only; changing user-facing rules belongs in the versioned Model Core, not in a free-form supplement.

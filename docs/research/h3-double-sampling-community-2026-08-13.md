# MiniMax H3 Prompt and Double-Sampling Community Research

Research date: 2026-08-13. This note separates MiniMax's official prompt contract from ComfyUI inference and restoration techniques. It does not inspect the user's local prompt or workflow files.

## 1. Normative H3 prompt contract

The normative source is MiniMax's `h3-prompt-writing` skill at commit `8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea`, not later repository changes or community templates.

### Base modes

T2VA, I2VA, FL2VA and L2VA use the following fields, in this exact order:

1. `integrated_multimodal_description`
2. `overall_soundscape`
3. `non_diegetic_music`

T2VA starts directly with those fields. I2VA anchors Picture 1 at 0.00 seconds and develops forward. FL2VA connects a first-frame and last-frame anchor through observable intermediate changes, normally in one continuous shot. L2VA infers a plausible earlier state and converges to Picture 1 as the actual final frame. I2VA/FL2VA/L2VA require their prescribed alignment line before the three fields. Shot 1 has no timestamp; later cuts use increasing `[Shot N] At MM:SS.mmm` times within the requested duration. Camera motion should be expressed as a natural action, optionally combining type, meaningful amplitude and meaningful speed. [Official skill](https://github.com/MiniMax-AI/MiniMax-H3/blob/8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea/skills/h3-prompt-writing/SKILL.md), [base-mode guide](https://github.com/MiniMax-AI/MiniMax-H3/blob/8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea/skills/h3-prompt-writing/references/base-en.txt)

### Full-reference mode

Ref2VA instead uses six ordered sections: `subject_definitions`, `summary`, `retention_analysis`, `detailed_description`, `overall_soundscape`, and `non_diegetic_music`. `<Subject N>` identifies reused visible content; `<Picture N>` is reserved for a concrete frame/composition anchor; `<Video N>` represents source-video editing, continuation, or temporal/camera structure; `<Audio N>` represents an actually reused or referenced audio signal. A video merely having audio is not sufficient to create an Audio label. Retention intent is made auditable with visible-content and audio retention levels. [Full-reference guide](https://github.com/MiniMax-AI/MiniMax-H3/blob/8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea/skills/h3-prompt-writing/references/ref-en.txt)

All rewrite prose is English, while dialogue/lyrics inside `<d>` and visible scene text retain their original language. Stable `(S1)` speaker IDs, exact dialogue, diegetic sound, overall soundscape, and audience-only music are distinct concerns. The official skill defines no FPS, resolution, sampler, step count, denoise value, upscale model, or second-pass recipe; those belong to the workflow layer.

## 2. What “double sampling” usually means

Community workflows use this phrase for several materially different pipelines:

| Pattern | Actual operation | Main benefit | Main risk |
| --- | --- | --- | --- |
| Full-frame two-pass | Generate low/medium resolution, upscale, re-encode, sample again | Restores generated detail at target resolution | Second pass may alter identity, motion or composition |
| Region second pass | Detect/track face or subject, crop, refine, composite back | Gives small faces more effective pixels | Detection drift, seams, color mismatch |
| Restoration then upscale | Clean artifacts with a temporal video-restoration model, then enlarge | Conservative identity and temporal stability | Less creative detail recovery |
| Framewise image upscale | Split frames, apply an image upscaler, recombine | Simple and relatively cheap | Flicker because frames are processed independently |

This taxonomy should be used before comparing settings. A second KSampler, a face-detail pass, and a temporal super-resolution model are not interchangeable.

## 3. Verified workflow patterns

### Full-frame second pass

Cubiq's ComfyUI workflow repository documents the classic approach: upscale pixels or latents, then use the lowest denoise that restores acceptable detail. Pixel/model-upscaled sources commonly need less denoise than raw latent upscales; the guide's examples use about `0.25` for a good model-upscaled pixel source, while noisy latent upscales may need `0.55` or more. This is a useful tuning principle, not a universal H3 parameter. Tile ControlNet can preserve source color/layout while allowing a stronger second pass. [ComfyUI Workflows upscale guide](https://github.com/cubiq/ComfyUI_Workflows/blob/main/upscale/README.md)

A concrete video example on Hugging Face generates LTX Video 2.3 at 1280×720, upscales the first pass to 1920×1080 using NVIDIA RTX VSR, re-encodes it, then performs an eight-step second sample. It also uses memory patches, so this is model-specific proof of the architecture, not a drop-in H3 recipe. [LTX 2.3 I2V two-pass workflow](https://huggingface.co/datasets/Cseti/ComfyUI-Workflows/blob/main/ltx/2.3/i2v-two-pass/README.md)

**Pros:** coherent whole-frame refinement; straightforward graph; prompt can reinforce wanted detail. **Cons:** expensive; global resampling can invent texture, modify a face, or destabilize motion. Preserve identity by lowering second-pass denoise and carrying the same reference/conditioning into pass two.

### Tracked face/subject refinement

The most defensible solution for a distant or blurry person is not repeatedly sampling the full frame. A WAN 2.2 example detects and segments faces with SAM2, crops the face sequence, performs a focused video-to-video generation pass, and composites it back. [WAN 2.2 face-detail workflow](https://huggingface.co/datasets/Cseti/ComfyUI-Workflows/blob/main/wan/2.2/face-detailer/README.md)

A broader WAN pipeline detects individual subjects/faces, crops them, applies pixel upscalers, refines with low-denoise video-to-video, composites the result, and only then applies RIFE interpolation. Its published example uses denoise `0.3`, recommends selecting the detected face index explicitly, and reduces temporal context on sub-16 GB GPUs. [WAN 2.2 per-subject upscaling](https://huggingface.co/datasets/Cseti/ComfyUI-Workflows/blob/main/wan/2.2/upscaling/README.md)

SCAIL-2 supplies a stronger temporal variant: track a stable square head crop, align a high-resolution face reference to the crop's face position/scale before the second pass, then feather/color-correct the composite. A fixed crop canvas reduces camera jitter; reference pre-alignment reduces layout work the generative pass must do. [SCAIL-2 multi-condition workflow](https://github.com/TTPlanetPig/comfyui_scail2_multi_cond)

Impact Pack's FaceDetailer is strong for still images and officially describes both two-pass damaged-face recovery and progressive iterative upscale. However, its own code warns that ordinary FaceDetailer is not designed for video and directs video users to the AnimateDiff-oriented detailer. Applying independent still-image face repair to every frame is therefore a flicker risk. [Impact Pack documentation](https://github.com/comfyorg/comfyui-impact-pack), [video warning in source change](https://github.com/ltdrdata/ComfyUI-Impact-Pack/pull/1053/files)

**Pros:** spends resolution and denoising budget on the person; can preserve the background; high-resolution face references materially help. **Cons:** substantially more nodes and VRAM; incorrect face selection or unstable masks create identity swaps and seams. Track masks/crops through time, keep crop size stable, align the reference, and feather plus color-match when compositing.

### Temporal restoration and super-resolution

ComfyUI's official upscaling guide distinguishes conservative from creative processing. Conservative models preserve identity and temporal consistency; creative diffusion upscalers can add detail but may hallucinate or flicker. It recommends fixing AI-video artifacts first, then upscaling to 1080p, and only then progressing toward 4K. It identifies SeedVR2 for high-fidelity restoration and FlashVSR for speed. [Official ComfyUI video-upscale guide](https://docs.comfy.org/tutorials/utility/video-upscale)

SeedVR2 is a one-step diffusion-transformer video restoration model designed for arbitrary-resolution restoration; ComfyUI has an official workflow template using a 3B INT8 variant, default 2× scale, and short-segment processing for long videos. [SeedVR2 official repository](https://github.com/IceClear/SeedVR2), [ComfyUI workflow template](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/utility_seedvr2_3b_int8_upscale_video.json)

FlashVSR is optimized primarily for 4× streaming super-resolution. Its authors warn that early third-party ComfyUI implementations omitted the Locality-Constrained Sparse Attention module, degrading fine detail and increasing aliasing/artifacts. They identify `smthemex/ComfyUI_FlashVSR` as closer to the official pipeline, while marking other implementations as modified, untested, or known-problematic. Its block-sparse backend has confirmed but hardware-specific support, so installation and results must be verified on the target GPU. [FlashVSR official repository](https://github.com/OpenImagingLab/FlashVSR)

**Pros:** temporal models are the safest general answer to flicker and mild blur; simpler than a second generative video pass. **Cons:** restoration cannot recover a face that never had sufficient structural information; large upscale ratios may create synthetic texture or exceed VRAM. Prefer 2× stages and short clips over a single extreme pass.

## 4. Community platform evidence and limitations

RunningHub has a minimal video-upscale graph consisting of video load → model-based image upscale/resize → video combine. This is accessible and inexpensive, but its node list exposes no temporal model, subject tracking, or second generative pass, so the claim “without quality loss” should not be treated as technical evidence of identity/temporal preservation. [RunningHub Upscale Video](https://www.runninghub.ai/post/1893781509206355969)

Another RunningHub HD-restoration workflow uses `ImageUpscaleWithModel`, VAE encode/decode and `BNK_TiledKSampler`, which is recognizable as tiled upscale plus a diffusion refinement pass. It is an image workflow and does not prove temporal consistency for video. [RunningHub HD repair](https://www.runninghub.ai/post/1778256484321255425)

RunningHub's indexed video-face-restoration listing exposes a segmentation/masked WAN VACE pass with a low-noise LoRA and explicitly rejects 1080p input in favor of 1024/832/512, illustrating that a face-refinement stage can have strict latent-resolution constraints. The detail page timed out when reopened, so this is discovery evidence from RunningHub's own indexed listing rather than a downloaded and independently inspected graph. [RunningHub video face restoration](https://www.runninghub.ai/post/1972539638483251202)

Civitai's direct model/workflow pages and API were not retrievable in this research environment. Search results expose community WAN I2V/upscale and FaceDetailer workflows, but their settings could not be verified from the owning page. No Civitai-specific numeric recommendation is therefore promoted into the conclusions.

## 5. Practical recommendation hierarchy

1. **Mild blur, identity already correct:** use SeedVR2 or another conservative temporal restorer at 2×; inspect a short clip before the full render.
2. **Small/distant face lacks pixels:** track and crop the head/face, pre-align a high-resolution identity reference, perform a low-denoise temporal V2V/detail pass, feather and color-match the composite.
3. **Whole video needs richer texture:** perform a 720p/medium-resolution first generation, upscale, re-encode, and apply a low-denoise second pass with the same prompt and references.
4. **Need 4K:** repair first, reach 1080p, then upscale progressively. Do not expect one 4×/8× framewise pass to fix identity.
5. **Avoid as the default:** independent FaceDetailer/GFPGAN/CodeFormer processing on every frame. It may sharpen faces but often changes them differently frame to frame.

For an H3-oriented product, keep the official H3 prompt renderer unchanged and treat pass-two instructions as workflow metadata: target region, preservation strength, reference reuse, output size, denoise, temporal context, mask feather, and color correction. Do not inject sampler/upscale folklore into the official prompt fields or label it as MiniMax guidance.

## 6. User-supplied prompt templates versus the current Studio

The supplied `基础版提示词模板.md` is 34,309 characters / roughly 5,244 whitespace-delimited words. It is principally an executable restatement of MiniMax's Ref2VA guide: six ordered sections, label ownership, task-type prefixes, visual/audio retention markers, shot syntax, speaker IDs, dialogue, soundscape/music separation, and complete examples. It adds a useful source-fidelity instruction but otherwise stays close to the official guide.

The supplied `R2VA加强版提示词模板.md` is 84,603 characters / roughly 12,434 words. It retains the same six-section protocol but adds 16 policy blocks: rewrite-versus-expansion authority, a silent intake checklist, digital-human/MV master-audio rules, reference-role isolation, multi-person anti-swap rules, camera prohibitions, typography/UI, product/brand factuality, style-medium logic, education and other specialized triggers, plus a final self-check and three longer examples. It contains 75 explicit `do not` rules and 39 `must` rules.

The current repository H3 Model Core is deliberately much smaller (about 2,693 source characters before the mode policy is appended). Runtime assembly adds the selected mode, duration, exact three/six-field contract, untrusted-data boundary, current Prompt/Session, Storyboard/Character/Manifest data, operation policy, output envelope, deterministic normalizers, and validators. Therefore raw prompt length alone understates current coverage.

| Dimension | Basic supplied template | Enhanced supplied template | Current APS implementation |
| --- | --- | --- | --- |
| Official protocol fidelity | Very strong, close to `ref-en.txt` | Strong, but surrounded by non-official policies | Strong protocol core plus executable validation |
| Prompt cost / small-model reliability | Medium-heavy | Very heavy; rule dilution and missed constraints are plausible on a 9B model | Lowest recurring context cost |
| Reference and audio semantics | Strong official baseline | Excellent for MV, lip-sync, master audio and multiple people | Main official invariants enforced; content guidance is terser |
| Creative authority | Mostly rewrite oriented | Explicit conversion-only versus expansion gate | Operation policy distinguishes CREATE/REFINE, but lacks an equally explicit content-level expansion gate |
| Product/UI/brand work | Sparse | Detailed and practical | Not a core H3 specialization today |
| Multi-turn edits | No persistent state; full prompt must be resubmitted | Same, with even larger reprocessing cost | Persistent current Prompt and revisions; failed updates preserve the prior result |
| Failure detection | Depends on the LLM self-check | Depends on a longer LLM self-check | Python checks format, timing, English body, media limits, labels, retention modality and identity anchors |

### What should be borrowed

The best additions are not the whole enhanced prompt. Add compact, testable content policies for: (1) conversion-only versus explicitly authorized expansion; (2) latest-approved-asset supersession; (3) master-audio window and visible-performance/lip-sync ownership; (4) multi-person screen-side and costume anti-swap continuity; and (5) strict separation of person, scene, product, typography and storyboard reference roles. Product/UI/education recipes should remain optional Markdown references selected for that task, not permanent Model Core text.

### What should not be copied into the core

Do not permanently inject the enhanced template's full specialized-design catalogue, long examples, brand campaign defaults, inferred dialogue/lyrics behavior, or repeated prohibitions. These increase token cost, create competing instructions, and can cause a local 9B model to optimize the checklist instead of the user's video. Examples are especially prone to leaking their subjects, camera moves or soundtrack into unrelated output. The official skill itself is a short router to mode-specific references rather than one monolithic prompt.

## 7. The supplied 123-node H3 double-sampling workflow

The supplied JSON contains 123 nodes, 120 links and 18 groups. Its active default path is a real pixel-space two-pass H3 pipeline, not a simple post-upscaler:

1. `MiniMaxH3ReferenceToVideo` builds conditioning and joint audiovisual latent at first-pass `ResolutionSelector` scale `0.4` (16:9), using up to nine pictures, one video and three audio inputs.
2. First sampling uses a Ref2VA INT8 model, Euler, beta scheduler, nominally 12 steps, and a chained turbo LoRA configuration. The graph contains old/new acceleration and cache groups, several currently bypassed.
3. The first sampled video latent is VAE-decoded to pixels; audio latent is separately decoded.
4. `ImageResizeKJv2` resizes the decoded frames to the second-pass 16:9 scale `0.6` using NVIDIA RTX VSR. This is pixel-space enlargement, so the VAE round trip deliberately creates a new target-resolution latent rather than resizing the original latent tensor.
5. The enlarged frames are VAE-encoded; decoded audio is also re-encoded; `PT_H3ConcatAVLatent` reconstructs a joint audiovisual latent.
6. A second, separate `minimax_h3_ref2va_pruned_w4a8_mixed` UNet uses the same positive conditioning and same random-noise source, `res_multistep`, a beta scheduler with terminal setting `0.2`, and nominally four steps. The final video is decoded while first-pass audio is reused for output.

This architecture can add target-resolution detail, but it is comparatively aggressive: pass two samples the entire spatiotemporal field with another model. It is not guaranteed to preserve a small face, because the enlarged first pass may still contain too few facial pixels and the second model is free to reinterpret them. The shared noise seed does not by itself guarantee identity preservation. The workflow also ships with many bypassed optional branches, two model families, custom memory/cache nodes and a warning that reference short-edge resolution must be manually matched to output; portability and reproducibility are therefore weaker than the graph title suggests.

## 8. Recommended experiments for this workflow

Run a small controlled matrix before adopting it as the default:

| Variant | Purpose |
| --- | --- |
| First pass only | Establish whether blur already exists before resizing |
| Current 0.4 → 0.6 second pass | Baseline supplied recipe |
| 0.5 → 0.6, same seed/references | Give faces more first-pass pixels and reduce pass-two burden |
| Current first pass → SeedVR2 2× | Compare conservative temporal restoration against generative redraw |
| Current two-pass → SeedVR2 | Test whether restoration after redraw improves texture without identity drift |
| Tracked face crop + low-denoise temporal V2V | Use when the face is small or structurally missing |

Judge each variant on face identity, eye/mouth stability, clothing/reference retention, motion continuity, background flicker, audio synchronization, peak VRAM and runtime. Do not judge only a single attractive frame. For the user's 8 GB GPU, begin with short 4–6 second clips, 2× or 720p→1080p restoration, tiled VAE/offload, and the smallest temporal batch that still preserves continuity.

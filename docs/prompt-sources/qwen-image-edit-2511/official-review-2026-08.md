# Qwen Image Edit 2511 Official Review — 2026-08

Primary sources: [QwenLM/Qwen-Image](https://github.com/QwenLM/Qwen-Image) and its [official edit prompt enhancer](https://github.com/QwenLM/Qwen-Image/blob/main/src/examples/tools/prompt_utils.py).

## Verified Facts

- The official repository recommends prompt rewriting for editing stability and exposes `polish_edit_prompt` as the reference implementation.
- Clear add/delete/replace instructions retain intent; vague requests receive only minimal visual detail.
- Visible text remains in its original language/case inside English double quotes.
- Human edits preserve core identity; changed appearance must fit the original image, and expression/beauty changes remain subtle.
- Style transfer names the source/target and describes key visible style features. Inpainting, outpainting, colorization, and multi-image edits have distinct handling.
- Multi-image instructions explicitly identify which image supplies the edited subject/style/background. The official 2511 serving example uses `Figure 1`/`Figure 2`; the enhancer examples also use `Picture 1`/`Picture 2`, so label vocabulary depends on the integration while index binding must stay exact.

## Local Diff

- `unchanged`: direct, specific edit action; object/position/count; quoted visible text; and explicit multi-image references.
- `new`: task-type policies for inpaint/outpaint/colorize, subtle facial edits, style-transfer extraction, and explicit unchanged-content clauses.
- `new`: the official code uses image understanding during rewrite. The current Composer only receives a manifest/text reference summary, so it cannot truthfully claim equivalent visual prompt enhancement.
- `unsupported local assumption`: one generic Skill is currently reused for generate/expand/rewrite/translate/repair; official guidance distinguishes task types and minimum-change behavior.

These gaps require typed Qwen edit semantics and a true image-aware route in a later phase, not a larger monolithic system prompt.

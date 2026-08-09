# ANIMA Official Review — 2026-08

Primary source: [CircleStone Labs ANIMA model card](https://huggingface.co/circlestone-labs/Anima).

## Verified Facts

- Base is the flexible training/fine-tuning foundation; Aesthetic raises default consistency; Turbo is distilled and officially uses CFG 1 with 8–12 steps.
- Base generation guidance is 30–50 steps and CFG 4–5.
- Training includes Danbooru-style tags, natural captions, and mixtures. Tags are lowercase with spaces; only `score_*` retains underscores.
- The published positive prefix includes `masterpiece, best quality, score_7, safe`; the published negative contains the current Base negative core.
- Aesthetic strips quality tags and recommends avoiding `score_*` in both positive and negative prompts.
- Official tag order is quality/meta/year/safety, count, character, series, artist, general; artist tags require `@`.

## Local Diff

- `unchanged`: Base 40 steps/CFG 5, Turbo 10 steps/CFG 1, Base negative, tag normalization/order, artist prefix, and Aesthetic score warnings.
- `unchanged`: natural-language mode is valid; the official card explicitly describes natural captions and mixed prompting.
- `product override`: local `safety_tag=none` omits `safe` unless the user explicitly selects it. This differs from the recommended official prefix but is intentionally user-controlled and must not be described as the official default.
- `unsupported local assumption`: the renderer’s Aesthetic CFG 4.5 is inside general guidance but is not an Aesthetic-specific official value.

No P3 Model Core change is made from inference; later revisions should cite this ledger entry.

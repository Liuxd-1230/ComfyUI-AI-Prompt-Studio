# CharacterBook / Storyboard Acceptance — 2026-08-12

## Scope

This work unit covers the CharacterBook → Storyboard Builder → Storyboard Select/H3 handoff. It does not run an image or video generator and does not unload the local LLM.

## Deterministic checks

- CharacterBook role tables preserve `character_id`, Speaker ID, stable/current/variable categories, source evidence, and lock-safe uncertainty handling.
- Storyboard output declares `character_definitions` for names that are not already in the book.
- `audio` is accepted at both shot and beat level and survives JSON round-trip.
- The builder enforces `max_scenes`, unique scene/shot/beat IDs, selectable empty scenes, and an exact target duration after parsing. Every truncation or repair is emitted through `continuity`.
- CharacterBook names are authoritative when binding known IDs; H3 conversion uses Storyboard character definitions for new IDs.
- Storyboard Select scene/shot text includes summary, action, camera, duration, audio, and beat labels.

## Real local run

Model: `qwen3.5-9b-uncensored-hauhaucs-aggressive` through LM Studio at `127.0.0.1:1234`.

Input story: a rainy-night station reunion between 小凛 and her older brother 阿岚, with a blue coat and a six-second target.

Observed result on the production `APS_StoryboardBuilder`: one scene, three shots, total duration `6.0s`, both `char_rin` and `char_aran` retained, both display names present in `character_definitions`, and shot-level audio preserved. The first request from the same local model returned non-JSON; the node took its documented lossless fallback (original story kept, no guessed character facts), and a second request succeeded without code changes. The local instance remained loaded throughout.

## Verification

`python -m pytest tests/ -q` passed; `python -m compileall nodes services renderers validators schemas server tests` passed; all four web JavaScript `node --check` commands passed.

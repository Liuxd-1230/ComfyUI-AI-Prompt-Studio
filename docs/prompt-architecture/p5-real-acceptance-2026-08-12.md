# P5 Real ComfyUI / LM Studio Acceptance — 2026-08-12

## Environment

- ComfyUI 0.32.0 on local port 8188.
- LM Studio model `qwen3.5-9b-uncensored-hauhaucs-aggressive`.
- Existing profile `LM [prof_159cd362]`, unload policy `never`.
- Public `APS_PromptStudio` in ANIMA Base lenient mode; no downstream image model.

## Executed paths

1. CREATE completed in 23.07 s and committed session
   `psess_492e72c39cc8`, node `42`, revision 1. The English prompt retained the
   requested silver-haired, blue-eyed girl, transparent umbrella, rainy Tokyo neon
   alley and composition. Validation passed with one non-blocking natural-language
   prefix warning and no repair.
2. REFINE completed in about 24.5 s and changed only the lighting to cyan/magenta.
   Character, umbrella, framing, location and rainy-night facts remained present;
   revision 2 committed with no repair.
3. The revision-2 workflow Session was queued through copied node `99` with the same
   message nonce. It made no model call, retained revision 2, forked session
   `psess_0edbed107d00`, and recorded the original session in `origin_session_id`.
4. A deliberately stale revision-1 request completed after revision 2 existed. The
   durable journal rejected it with `JournalConflict: base v1, latest v2`; the stored
   cyan/magenta revision-2 snapshot remained unchanged.
5. A workflow containing revision 1 was opened in the real ComfyUI frontend. The
   native recovery confirmation offered revision 2; accepting it restored the full
   two-turn conversation and exact cyan/magenta prompt into the node widget.

## Persistence evidence

The successful snapshot was written to
`user/ai_prompt_studio/recovery-journal.json`. A fresh journal adapter retrieved the
same revision. The browser recovery path validates session/node identity, only offers
strictly newer revisions, supports explicit discard, and marks accepted writeback for
workflow saving. Console review showed no AI Prompt Studio error; unrelated ComfyUI
Manager and third-party extension deprecation/preload warnings were present.

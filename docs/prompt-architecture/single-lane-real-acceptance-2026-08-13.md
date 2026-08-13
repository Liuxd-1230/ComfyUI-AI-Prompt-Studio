# Single-Lane Studio Real Acceptance — 2026-08-13

## Setup

Production node classes were executed directly through the real Gateway without an
image/video generator. Profiles: 基元 (`deepseek-v4-flash-0731`, Responses,
reasoning high) and LM Studio (`qwen3.5-9b-uncensored-hauhaucs-aggressive`, reasoning
high). LM remained loaded. Each profile ran Image CREATE → REFINE and H3 T2VA CREATE
→ REFINE using the same high-constraint Rose/train task.

## Result

| Profile | Total | Image | H3 |
|---|---:|---|---|
| 基元 | 47.06s | CREATE/REFINE passed; warm-light-only edit retained identity, dress, blank letter, window and composition | CREATE/REFINE passed; push-in → truck-right edit retained all story, identity, action, audio and no-music facts |
| LM | 37.87s | CREATE/REFINE passed with the same fact retention | CREATE/REFINE passed with the same fact retention |

Both ANIMA results were English and received the deterministic
`masterpiece, best quality, score_7` prefix. The negative output contained the official
base list plus the explicit `watermark, extra fingers` exclusion. Both H3 outputs used
the three required fields and passed deterministic validation.

The run found one real quality defect: LM placed an inferred smell in
`overall_soundscape`. The Model Core now explicitly limits that field to audible facts,
and `h3_soundscape_non_audible` rejects smell/scent/odor/taste language, triggering the
single bounded repair rather than committing a false-positive prompt.

After that change, LM H3 was rerun live in 9.34s. It produced only train engine/wheel,
paper, and rain sounds, preserved every requested visual/action fact, required no repair,
and passed with one harmless deterministic heading-normalization warning.

## Conclusion

The one-lane design retains the useful output qualities previously observed across the
two lanes while removing the structured-plan latency and false-green failure mode. 基元
remains richer and more cinematic; LM is shorter and faster. Both are usable for
iterative prompt-only workflows.

# MiniMax H3 Official Review — 2026-08

Primary sources are pinned to official commit `8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea`: [Skill](https://github.com/MiniMax-AI/MiniMax-H3/blob/8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea/skills/h3-prompt-writing/SKILL.md), [base guide](https://github.com/MiniMax-AI/MiniMax-H3/blob/8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea/skills/h3-prompt-writing/references/base-en.txt), [Ref2VA guide](https://github.com/MiniMax-AI/MiniMax-H3/blob/8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea/skills/h3-prompt-writing/references/ref-en.txt), and [README](https://github.com/MiniMax-AI/MiniMax-H3/blob/8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea/README.md).

## Verified Facts

- Output duration is 4–15 seconds. Ref2VA accepts at most 9 images, 3 videos, 3 audio clips, and 12 mixed files; video/audio clips are each 2–15 seconds and each modality totals at most 15 seconds. Audio cannot be the only input.
- Base modes use three ordered fields. Shot 1 has no timestamp; later cut times strictly increase within duration.
- Camera semantics distinguish focal change from physical translation and encode meaningful type/amplitude/speed.
- Speaker IDs are global and stable. Dialogue is verbatim; voiceover requires the exact off-screen semantics and closed lips; cross-cut and end truncation use their markers.
- Ref2VA has six ordered sections. Labels retain meaning, visual/audio retention markers differ, and each reference must take effect at an exact shot/location.
- Soundscape and non-diegetic music have distinct ownership; soundscape is `N/A` only for explicitly requested total silence.

## Local Diff

- `unchanged`: current H3 plan, renderer, and validators cover the principal structure, duration, media counts/totals, timing, references, speakers, voiceover, soundscape, and marker modality.
- `new`: P3 formal semantic validation now checks the Plan before protocol rendering, including stable speaker/reference ownership and safe mechanical repair.
- `resolved in P6`: the former `H3_SYSTEM_PROMPT`/editable Skill overlap is replaced by one immutable `prompting/model_cores.py` H3 core. Markdown supplements remain optional, lower-priority guidance and cannot replace the protocol/schema/validator.
- `unsupported local assumption`: the removed `R2V` alias is not accepted; the official mode name is Ref2VA.

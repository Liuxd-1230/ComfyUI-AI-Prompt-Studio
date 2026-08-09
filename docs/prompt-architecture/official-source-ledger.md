# Official Source Ledger

Research date: 2026-08-09. Runtime code never fetches these pages. “Local status” compares the P3 repository state; evidence is recorded before any later Model Core update.

| Target | Primary source | Revision policy | Verified scope | Local status |
|---|---|---|---|---|
| ANIMA | [CircleStone Labs model card](https://huggingface.co/circlestone-labs/Anima) | official `main`, accessed date above | Base/Aesthetic/Turbo variants, generation settings, tag/natural-language prompting | mostly aligned; safety default is an intentional product override |
| Z-Image Turbo | [Tongyi-MAI model card](https://huggingface.co/Tongyi-MAI/Z-Image-Turbo) | official `main`, accessed date above | Turbo task, bilingual text, 8 NFEs, CFG 0, official example style | aligned on profile; local “longer is better” warning is unsupported |
| Qwen Image Edit 2511 | [QwenLM repository](https://github.com/QwenLM/Qwen-Image), [official prompt enhancer](https://github.com/QwenLM/Qwen-Image/blob/main/src/examples/tools/prompt_utils.py) | official `main`, accessed date above | prompt rewriting, editing task classes, identity/text/multi-image rules | local core is incomplete |
| MiniMax H3 | [official Skill](https://github.com/MiniMax-AI/MiniMax-H3/blob/8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea/skills/h3-prompt-writing/SKILL.md), [base guide](https://github.com/MiniMax-AI/MiniMax-H3/blob/8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea/skills/h3-prompt-writing/references/base-en.txt), [Ref2VA guide](https://github.com/MiniMax-AI/MiniMax-H3/blob/8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea/skills/h3-prompt-writing/references/ref-en.txt), [README](https://github.com/MiniMax-AI/MiniMax-H3/blob/8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea/README.md) | pinned `8d8824efaf94586c0cc9ac7ad8d0723d4d6420ea` | five modes, prompt structures, timing/audio/reference semantics, input limits | validators largely aligned; Model Core ownership remains duplicated |

## Change Classification

- `unchanged`: local rule and official evidence agree.
- `outdated`: local rule matched an older source but not the recorded source.
- `contradicted`: official evidence says the opposite.
- `new`: official rule is absent locally and should be evaluated for a later Model Core revision.
- `unsupported local assumption`: local behavior has no support in the reviewed official material.
- `product override`: deliberate UX policy that must remain visible rather than being presented as official behavior.

Detailed evidence and diffs live under `docs/prompt-sources/<target>/`. Community posts, third-party workflows, and search-result summaries were excluded.

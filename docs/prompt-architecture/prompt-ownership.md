# Prompt Ownership

Prompt content has one authoritative owner per semantic layer. Rendered request strings are compiled artifacts, never new sources of truth.

| Layer | Owner | May contain | Must not contain |
|---|---|---|---|
| Runtime Policy | production request assembler | injection boundary, language/response defaults, protocol-independent safety | target-model syntax, story facts |
| Node/Domain Core | production node/service | stable role and domain duties such as storyboard continuity | provider syntax, mutable user data |
| Target Model Core | `prompting/model_cores.py` | officially verified ANIMA, Z-Image, Qwen Edit, or H3 rules | operation-specific turn behavior |
| Operation Policy | `prompting/operation_policies.py` | create, refine, format repair, protocol retry, text/image observation | duplicated model rules or current plan data |
| Supplemental Guidance | versioned supplement references | optional project/team guidance | silent overrides of higher layers |
| Structured Task Data | typed context builder | current plan, books, manifest, history, user request, validation issues | executable system instructions |
| Output Contract | `prompting/output_contracts.py` | machine-readable JSON Schema, tagged envelope, JSON intent, derived provider fallback | hand-maintained duplicate schemas or model rules |

## Domain State Ownership

- `CharacterBook`, `CharacterBible`, `Storyboard`, and `ReferenceManifest` own source facts.
- Formal target plans own generation semantics; they reference source IDs instead of copying unlocked prose as competing truth.
- `PromptStudioSession`, revisions, `ChangeSet`, transaction records, and observations own execution history.
- `RenderedPrompt`, `GenerationProfile`, `ValidationReport`, and `PromptAssemblyReport` are derived results.

## Compatibility Boundary

ADR 0007 intentionally breaks the former frozen facade rule for the only current
user. `APS_PromptStudio` is now the public image owner and does not call the obsolete
Composer internally. `APS_H3PromptStudio` likewise owns the H3 public lifecycle;
the former Composer and Director source files are removed.

Both strict Studio lanes delegate REFINE to the canonical semantic transaction.
The former root patch, independent approval, Critic, and creative repair helpers
have been removed rather than retained as compatibility APIs.

## Mutation Authority

Only a validated transaction may commit a strict semantic plan. Declared requested
paths are mutation authority; model-proposed dependent paths are rejected unless a
trusted deterministic impact analyzer introduces them. Diff Guard, locks, target
renderer/validator, and revision CAS constrain the actual committed candidate.
Protocol repair is format-preserving and runs at most once; creative repair is not
an automatic stage.

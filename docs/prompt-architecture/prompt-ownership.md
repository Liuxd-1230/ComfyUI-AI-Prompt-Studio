# Prompt Ownership

Prompt content has one authoritative owner per semantic layer. Rendered request strings are compiled artifacts, never new sources of truth.

| Layer | Owner | May contain | Must not contain |
|---|---|---|---|
| Runtime Policy | prompt assembly runtime registry | injection boundary, language/response defaults, protocol-independent safety | target-model syntax, story facts |
| Node/Domain Core | node-domain registry | stable role and domain duties such as storyboard continuity | provider syntax, mutable user data |
| Target Model Core | model-core registry | officially verified ANIMA, Z-Image, Qwen Edit, or H3 rules | operation-specific repair/rewrite instructions |
| Operation Policy | operation registry | create, refine, audit, repair, translate behavior | duplicated model rules or current plan data |
| Supplemental Guidance | versioned supplement references | optional project/team guidance | silent overrides of higher layers |
| Structured Task Data | typed context builder | current plan, books, manifest, history, user request, validation issues | executable system instructions |
| Output Contract | schema registry | machine-readable JSON Schema and compatibility fallback | hand-maintained duplicate schemas |

## Domain State Ownership

- `CharacterBook`, `CharacterBible`, `Storyboard`, and `ReferenceManifest` own source facts.
- Formal target plans own generation semantics; they reference source IDs instead of copying unlocked prose as competing truth.
- `PromptStudioSession`, revisions, `ChangeSet`, transaction records, and observations own execution history.
- `RenderedPrompt`, `GenerationProfile`, `ValidationReport`, and `PromptAssemblyReport` are derived results.

## Compatibility Boundary

`APS_PromptComposer` and `APS_MiniMaxH3Director` remain one-shot public facades. Their class names, widget order, required input names, return types, and workflow JSON compatibility are frozen unless a migration is supplied. Stateful Studio nodes are separate consumers of the same adapters, renderers, and validators; they do not call a one-shot node internally.

Composer and H3 Director now delegate persistent REFINE to the canonical semantic
transaction. The old root-oriented patch helpers remain callable only for pre-P2
Python consumers and are not allowed in node execution paths.

## Mutation Authority

Only a validated transaction may commit a semantic plan. A requested change authorizes its dependency closure, not arbitrary regeneration. Each requested, dependent, invalidated, or conflicting fact carries a reason. Diff Guard, semantic validation, protocol validation, and bounded repair are independent stages.

The semantic Critic owns no facts and has no mutation authority. For high-risk
transactions it receives an affected before/after slice plus relevant locked
values and returns `SemanticIssue` records. A repair proposal is a separate
ChangeSet and must pass the same authorization, Diff Guard, semantic, and protocol
boundaries before the Session can commit.

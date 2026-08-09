# P2 Transaction and Data-Boundary Migration

## Safe Semantic Mutation

`schemas/changeset.py` defines a reasoned `ChangeSet`: base revision, intent scope, requested and dependent changes, invalidated facts, constraint conflicts, and summary. Every mutation requires an operation, semantic path, and reason.

`domain/transactions.py` applies changes to a normalized clone. It rejects malformed or stale revisions, unresolved conflicts, missing paths, unauthorized diffs, and deterministic semantic-check failures before calling the commit callback. List insertion/deletion authorizes only the affected list's structural index shift. The original plan therefore remains untouched on every failure path.

This is the canonical P2 mutation seam. The older root-oriented patch code remains only behind Composer/H3 workflow compatibility and is explicitly non-canonical.

## Live Prompt Boundary Migration

All creative calls now attach a `PromptAssemblyReport` to `GenerateRequest`; direct vision calls return the same report to their caller.

- LLM Generate keeps user system instructions in the supplemental system layer, while `context` is a labelled user-role task-data block.
- Reference Analyzer separates analysis/identity policy from text anchors, Character Bible data, image slots, and images. Vision requests now use an actual system message plus user multimodal data.
- Storyboard Builder sends story, limits, CharacterBook, and ReferenceManifest as structured data. Its live request no longer copies the JSON Schema into prose.
- Prompt Composer identifies each legacy Skill as a versioned migration source and sends prompt, book, references, and validation issues as distinct task-data blocks.
- H3 Director separates immutable protocol, editable strategy, operation policy, and typed request data. Live create/repair no longer use the legacy hand-copied JSON template.
- Transitional session refinement now uses the same assembly boundary and remains labelled as a legacy patch contract.

`build_storyboard_prompt()`, `build_plan_prompt()`, and `h3_system_prompt()` remain compatibility entry points for existing callers and tests. New live paths use structured builders; later phases may remove the legacy functions only with a documented migration.

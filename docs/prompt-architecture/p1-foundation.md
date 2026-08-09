# Persistent P1 Semantic Domain Foundation

P1 establishes executable boundaries without changing public node widgets or workflow serialization.

## Semantic Foundation

- `schemas/anima.py` is the authoritative ANIMA Plan Normal Form. The renderer re-exports its types for source compatibility.
- ANIMA Plan Normal Form v2 has one editable owner per important fact. Character identity and appearance live in `required_traits` / `variable_traits`, behavior in `action`, framing location in `position`, and non-character residual prose in `scene_description`. `creative_notes` and `supplemental_tags` are limited to facts that have no structured owner.
- The editable `AnimaCharacter.description`, `AnimaPromptPlan.natural_body`, `character_tags`, and `visual_tags` fields were removed. Natural, tags, and hybrid renderers now derive from the same formal Plan; tag rendering no longer depends on a parallel tag cache.
- `AnimaPromptPlan.validate()` applies one owner matrix to every structured, free-prose, and tag field, rejecting exact or contained duplicates. Semantic paraphrase detection belongs to the later critic phase; P1 does not claim that deterministic string checks understand synonyms. Prompt Composer sends detected violations through its existing one-repair validation path.
- v1 JSON and workflow sessions migrate through `ANIMA_NORMAL_FORM_MIGRATIONS`. Legacy `natural_body` alone becomes a global `creative_notes` item, and a standalone character `description` becomes a character-bound creative note—neither is guessed to be scene, action, or stable appearance. If legacy prose coexists with any other semantic owner, migration raises `AnimaMigrationConflict` before any revision changes. The user must start a new session or remove the conflicting legacy prose; the stable v1 session remains intact. Malformed character entries fail at the schema boundary with `SchemaError`. Successfully refined non-conflicting sessions persist v2.
- `AnimaPromptPlan.normalized()` provides deterministic trimming and de-duplication. ANIMA Skill output contracts emit v2 directly, and Prompt Composer exposes ownership violations through its normal validation and repair path.
- ANIMA and H3 plans expose compact `to_llm_context()` data. `request_plan_patch()` now uses the selected adapter instead of sending the full persisted session bundle, so final prompts, validation, generation profiles, provider output, warnings, generated IDs, and timestamps stay out of each REFINE request.
- `domain/plan_adapters.py` supplies real ANIMA and H3 adapters for loading, cloning, normalizing, and `to_llm_context()`. The former `llm_context()` spelling remains a compatibility alias.

## Prompt Assembly Foundation

`prompting/` implements ordered, versioned prompt sources for Runtime, Node Core, Model Core, Operation, and Supplemental layers. `StructuredTaskData` is rendered into labelled data blocks and cannot enter the compiled system string. `PromptAssemblyReport` records every source ID, version, scope, SHA-256 content hash, task-data ID, output-contract ID, and final assembly hash.

The core registry now owns the runtime untrusted-data boundary, storyboard domain role, and create/repair operation policies. Target Model Cores are registered only after P3 primary-source research; current legacy Skills continue to serve compatibility paths until P2 migration.

## Compatibility

Existing imports from `renderers.anima` and one-shot `render_anima(text, ...)` calls remain valid. Non-conflicting serialized PNF v1 content is migrated on the next refinement and committed as v2; conflicting content fails before Gateway/commit and preserves the old revision. Tests cover schema round-trip, safe/refused v1 migration, renderer output, Skill contracts, Composer validation, compact REFINE context, and workflow-session migration.

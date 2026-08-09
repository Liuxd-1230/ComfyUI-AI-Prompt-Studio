# P1 Foundation

P1 establishes executable boundaries without changing public node widgets or workflow serialization.

## Semantic Foundation

- `schemas/anima.py` is the authoritative ANIMA Plan Normal Form. The renderer re-exports its types for source compatibility.
- `AnimaPromptPlan.normalized()` provides deterministic trimming and de-duplication; `natural_body` is residual scene prose, while character identity, variable traits, action, and position belong to character records.
- ANIMA and H3 plans expose compact `to_llm_context()` data. Provider output, validation, warnings, generated IDs, and timestamps are excluded.
- `domain/plan_adapters.py` supplies real ANIMA and H3 adapters for loading, cloning, normalizing, and producing LLM context. Future Studio transactions select an adapter by family instead of branching throughout orchestration code.

## Prompt Assembly Foundation

`prompting/` implements ordered, versioned prompt sources for Runtime, Node Core, Model Core, Operation, and Supplemental layers. `StructuredTaskData` is rendered into labelled data blocks and cannot enter the compiled system string. `PromptAssemblyReport` records every source ID, version, scope, SHA-256 content hash, task-data ID, output-contract ID, and final assembly hash.

The core registry now owns the runtime untrusted-data boundary, storyboard domain role, and create/repair operation policies. Target Model Cores are registered only after P3 primary-source research; current legacy Skills continue to serve compatibility paths until P2 migration.

## Compatibility

Existing imports from `renderers.anima`, one-shot node contracts, and serialized session shapes remain valid. P1 adds typed foundations and tests; P2 moves live calls across the boundary.

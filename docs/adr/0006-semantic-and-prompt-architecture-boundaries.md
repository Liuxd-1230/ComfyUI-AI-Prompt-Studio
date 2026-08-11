# ADR 0006: Semantic and Prompt Architecture Boundaries

- Status: Accepted
- Date: 2026-08-09

> **2026-08-11 amendment:** ADR 0007 makes the semantic transaction pipeline the
> strict Studio lane rather than the universal path. New Studios use a lightweight
> tagged prompt contract by default. Routine independent intent approval and LLM
> Semantic Critic are removed; deterministic target checks remain mandatory.

## Context

Prompt rules, operation policies, task data, schemas, semantic plans, and persisted revisions currently overlap across nodes, Skills, renderers, and validators. String concatenation makes the final request difficult to inspect, while root-level plan replacement cannot prove minimum consistent change.

## Decision

Adopt two cooperating architectures:

1. A six-layer prompt compiler: Runtime Policy, Node/Domain Core, Target Model Core, Operation Policy, Supplemental Guidance, and Structured Task Data, followed by a separately owned output contract.
2. A typed semantic transaction pipeline: intent, reasoned `ChangeSet`, dependency/impact analysis, clone application, Diff Guard, normalization, semantic validation, optional risk-triggered critic, rendering, protocol validation, bounded repair, and atomic commit.

Source state, semantic state, execution state, and compiled results are distinct. PlanAdapters isolate target families. One-shot Composer and H3 Director remain compatibility facades; future Image/H3 Studio nodes use shared domain services directly.

## Consequences

Every model request becomes observable through a `PromptAssemblyReport`. Task data cannot be promoted to system instructions. Official Model Cores require primary-source evidence. Semantic edits may include justified dependent changes, but unauthorized diffs fail before commit. Migration proceeds incrementally behind existing node contracts.

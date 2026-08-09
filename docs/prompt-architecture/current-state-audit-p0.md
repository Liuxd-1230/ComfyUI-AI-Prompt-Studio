# P0 Current-State Audit

## Baseline

The repository has working one-shot generation, reference analysis, storyboard, image prompt composition, H3 planning, capability probing, runtime unload, and transitional persisted sessions. The public node contracts and existing workflow JSON files are compatibility boundaries.

## Transitional Session Code

| Component | P0 disposition | Reason |
|---|---|---|
| `services/prompt_session.py` session envelope | reuse through adapter | preserves saved workflows while formal execution state is introduced later |
| `request_plan_patch` and `PATCH_SCHEMA` | deprecate from canonical path | root replacement is not a semantic `ChangeSet` or dependency-aware transaction |
| Composer/H3 hidden session widgets | retain for compatibility | removing or reordering them would corrupt serialized workflows |
| Composer/H3 create/refine branches | refactor behind PlanAdapters | one-shot nodes remain facades; future Studio nodes own stateful interaction |
| `revert_previous()` destructive rollback | contain as debt | immutable revision/revert semantics belong to a later phase |
| `CREATE_POLICY`/`REFINE_POLICY` strings | migrate to operation registry | lifecycle rules need versioned, observable ownership |

## P0 Decisions

1. No UI redesign occurs in P0.
2. No official target rule is changed from memory; P3 records primary-source evidence first.
3. Formal plans, source state, execution state, and rendered output remain separate.
4. Prompt assembly must expose ordered sources, source versions/hashes, task-data labels, output contract, and final assembly hash.
5. Legacy Skills remain readable during migration, but no new mixed-responsibility Skill is accepted as architecture-complete.

## Compatibility Checks

Existing node registration, input order, return types, example workflow loading, direct one-shot behavior, and saved session round trips remain covered by the current suite. New architecture tests add inventory completeness and later assembly/transaction invariants without weakening those checks.

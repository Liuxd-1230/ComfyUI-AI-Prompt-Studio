# Persistent Contract Implementation Status

> **ADR 0007 transition:** the 2026-08-11 dual-lane amendments are binding, but the
> runtime is not migrated until the corresponding work units land. At this checkpoint
> the repository still registers the legacy Composer/Director and PromptSession v2;
> do not describe the new Studios or v3 as available yet.

This table tracks the binding Persistent contract §108 at the current HEAD.
“Partial” means the invariant has an executable base but the named end-to-end
surface is not complete; it must not be described as finished functionality.

| §108 | Status | Executable evidence / remaining gap |
|---|---|---|
| 108.1 Single Attribute Edit | done | `test_nodes_phase4.py`, scoped ChangeSet + Diff Guard |
| 108.2 Derived Description Synchronization | done | PNF has no editable derived prose; `test_phase1_architecture.py` |
| 108.3 Environment Invalidation | done | `test_phase3_semantics.py::test_anima_pnf_needs_no_derived_prose_cleanup_and_blocks_stale_lighting` |
| 108.4 Positive / Negative Conflict | done | deterministic negative cleanup in `test_phase2_transactions.py` and node production regression |
| 108.5 H3 Timing Dependency | done | proportional timestamp closure in transaction and H3 node tests |
| 108.6 Delete Middle Shot | partial | guarded collection edits exist; dedicated reindex end-to-end regression remains |
| 108.7 Object State | done | drop→hold invariant in `test_phase3_semantics.py` |
| 108.8 Intentional Surreal Transition | partial | broad authorization exists; dedicated surreal-transition regression remains |
| 108.9 Unauthorized Changes | done | independent path approval + adversarial transaction tests |
| 108.10 Malformed Patch | done | bounded structured retry in `test_p41_resilience.py` |
| 108.11 Validator Failure | done | production commit spies in Composer/H3 node tests |
| 108.12 Repair Failure | done | one-pass repair and no-commit production tests |
| 108.13 No New Message | done | nonce/empty zero-call tests in Composer and H3 |
| 108.14 Stale Concurrent Result | done | revision CAS plus node commit-spy tests; journal CAS in `test_recovery_journal.py` |
| 108.15 Restore | done | immutable restore-as-new-revision tests in `test_prompt_session.py` |
| 108.16 Workflow Reload | done | serialized Session → new node instance → REFINE regression |
| 108.17 Node Copy | partial | Session/node journal key seam exists; durable copied-node writeback is P5 |
| 108.18 Skill Changed | done | bound fingerprint mismatch tests |
| 108.19 CharacterBible Changed | done | same-nonce mismatch-before-Gateway production test |
| 108.20 Storyboard Major Change | done | source fingerprint comparison; finer compatibility/rebase is not implemented |
| 108.21 Target Compatible Switch | partial | changes are detected; automatic compatible migration/rebase is not implemented |
| 108.22 Target Incompatible Switch | done | blocked unless explicit New Session |
| 108.23 Long Conversation | done | explicit conversation/revision caps in `test_prompt_session.py` |
| 108.24 Workflow Size | partial | bounded Session payload; no repository-wide size budget regression yet |
| 108.25 Prompt Injection in Storyboard | done | external context is task data, not executable instruction; prompt inventory tests |
| 108.26 Prompt Injection in Skill | partial | source ownership/assembly boundaries exist; dedicated hostile-Skill regression remains |
| 108.27 ZIP Path Traversal | done | attachment traversal regression in `test_attachments.py` |
| 108.28 Skill Scripts | done | YAML-only Skill validation; scripts are not executed |
| 108.29 Style Conflict | done | deterministic semantic test in `test_phase3_semantics.py` |
| 108.30 Style Identity Lock | partial | stable fact locks exist; dedicated style/identity production regression remains |

The Recovery Journal currently defines and proves the clean interface only.
Durable workflow writeback, crash recovery, and copied-node branch UX remain P5
work and are intentionally reported as unfinished.

## Known Phase Gaps Outside §108

- `PlanAdapter` currently owns typed load/normalize/context/clone/dump only. The
  complete §13/§109 propose/validate/apply/render/protocol/repair façade and dedicated
  Studio nodes are not implemented; Composer/H3 remain compatibility facades.
- Recovery Journal has a tested clean interface but is not connected to durable
  backend storage or frontend recovery prompts.
- Automatic fingerprint Rebase/target migration is not implemented; mismatches
  preserve the stable revision and require New Session or an existing restore.

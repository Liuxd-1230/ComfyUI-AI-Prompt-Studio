# Persistent Contract Implementation Status

> **ADR 0007 transition:** the 2026-08-11 dual-lane amendments are binding, but the
> ADR 0007 runtime migration is implemented: PromptSession v3, the lenient protocol
> parser, `APS_PromptStudio`, and `APS_H3PromptStudio` are registered and tested.
> The former Composer/Director implementations are removed. Real ComfyUI/LM Studio
> prompt-only acceptance remains required before the whole refactor is declared done.

This table tracks the binding Persistent contract §108 at the current HEAD.
“Partial” means the invariant has an executable base but the named end-to-end
surface is not complete; it must not be described as finished functionality.

| §108 | Status | Executable evidence / remaining gap |
|---|---|---|
| 108.1 Single Attribute Edit | done | strict Studio scoped ChangeSet + Diff Guard regressions |
| 108.2 Derived Description Synchronization | done | PNF has no editable derived prose; `test_phase1_architecture.py` |
| 108.3 Environment Invalidation | done | PNF ownership plus strict candidate validation |
| 108.4 Positive / Negative Conflict | done | deterministic negative cleanup in `test_phase2_transactions.py` and Studio failure regression |
| 108.5 H3 Timing Dependency | done | proportional timestamp closure in transaction and H3 Studio tests |
| 108.6 Delete Middle Shot | partial | guarded collection edits exist; dedicated reindex end-to-end regression remains |
| 108.7 Object State | partial | no LLM Critic under ADR 0007; protocol validator covers representable hard conflicts only |
| 108.8 Intentional Surreal Transition | done | creative interpretation remains with the selected model; strict mode guards only declared mutations |
| 108.9 Unauthorized Changes | done | declared requested paths + Diff Guard; model-proposed dependencies are rejected |
| 108.10 Malformed Patch | done | bounded structured retry in `test_p41_resilience.py` |
| 108.11 Validator Failure | done | image/H3 Studio production failures do not commit or creatively repair |
| 108.12 Repair Failure | done | one protocol-format retry maximum; failed retry leaves stable Session unchanged |
| 108.13 No New Message | done | nonce/empty zero-call tests in both Studio nodes |
| 108.14 Stale Concurrent Result | done | revision CAS plus node commit-spy tests; journal CAS in `test_recovery_journal.py` |
| 108.15 Restore | done | immutable restore-as-new-revision tests in `test_prompt_session.py` |
| 108.16 Workflow Reload | done | serialized v3 Session → new node instance → REFINE regression |
| 108.17 Node Copy | partial | Session/node journal key seam exists; durable copied-node writeback is P5 |
| 108.18 Skill Changed | done | bound fingerprint mismatch tests |
| 108.19 CharacterBible Changed | done | same-nonce mismatch-before-Gateway production test |
| 108.20 Storyboard Major Change | done | source fingerprint comparison; finer compatibility/rebase is not implemented |
| 108.21 Target Compatible Switch | done | lenient target changes warn and continue; strict changes require a successful new lineage |
| 108.22 Target Incompatible Switch | done | strict mode creates a replacement lineage only after successful CREATE |
| 108.23 Long Conversation | done | explicit conversation/revision caps in `test_prompt_session.py` |
| 108.24 Workflow Size | partial | bounded Session payload; no repository-wide size budget regression yet |
| 108.25 Prompt Injection in Storyboard | done | external context is task data, not executable instruction; prompt inventory tests |
| 108.26 Prompt Injection in Skill | partial | source ownership/assembly boundaries exist; dedicated hostile-Skill regression remains |
| 108.27 ZIP Path Traversal | done | attachment traversal regression in `test_attachments.py` |
| 108.28 Skill Scripts | done | YAML-only Skill validation; scripts are not executed |
| 108.29 Style Conflict | partial | deterministic renderer/validator checks remain; creative Critic was removed by ADR 0007 |
| 108.30 Style Identity Lock | partial | stable fact locks exist; dedicated style/identity production regression remains |

The Recovery Journal currently defines and proves the clean interface only.
Durable workflow writeback, crash recovery, and copied-node branch UX remain P5
work and are intentionally reported as unfinished.

## Known Phase Gaps Outside §108

- Both Studio nodes use their selected freeform or typed transaction lane end to end;
  neither calls an obsolete one-shot node.
- Recovery Journal has a tested clean interface but is not connected to durable
  backend storage or frontend recovery prompts.
- Automatic fingerprint Rebase/target migration is not implemented; mismatches
  preserve the stable revision and require New Session or an existing restore.

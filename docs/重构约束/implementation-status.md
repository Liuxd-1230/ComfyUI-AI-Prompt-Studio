# Persistent Contract Implementation Status

> **ADR 0007 transition:** the 2026-08-11 dual-lane amendments are binding, but the
> ADR 0007 runtime migration is implemented: PromptSession v3.1, the lenient protocol
> parser, `APS_PromptStudio`, and `APS_H3PromptStudio` are registered and tested.
> The former Composer/Director implementations are removed. The 2026-08-11 real
> ComfyUI/LM Studio prompt-only matrix passed for image/H3 lenient and strict
> CREATE/REFINE, two consecutive lenient refinements, untagged output, explicit mode
> switch, and restore. The local model would not emit deliberately truncated JSON/tag
> output, so that provider-dependent live fault injection remains open; the same public
> node failure seam is covered deterministically in `test_p41_resilience.py` and
> `test_h3_prompt_studio.py`. See `docs/prompt-architecture/p4.1-real-acceptance-2026-08-11.md`.

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
| 108.6 Delete Middle Shot | done | H3 adapter reindexes list items after guarded middle-shot deletion; public strict-node regression covers rendered Shot 1/2 output |
| 108.7 Object State | partial | no LLM Critic under ADR 0007; protocol validator covers representable hard conflicts only |
| 108.8 Intentional Surreal Transition | done | creative interpretation remains with the selected model; strict mode guards only declared mutations |
| 108.9 Unauthorized Changes | done | declared requested paths + Diff Guard; model-proposed dependencies are rejected |
| 108.10 Malformed Patch | done | bounded structured retry in `test_p41_resilience.py` |
| 108.11 Validator Failure | done | image/H3 Studio production failures do not commit or creatively repair |
| 108.12 Repair Failure | done | one protocol-format retry maximum; failed retry leaves stable Session unchanged |
| 108.13 No New Message | done | nonce/empty zero-call tests in both Studio nodes |
| 108.14 Stale Concurrent Result | done | revision CAS, durable fresh-read journal CAS, node commit-spy tests, and real 9B stale-result rejection |
| 108.15 Restore | done | immutable restore-as-new-revision tests in `test_prompt_session.py` |
| 108.16 Workflow Reload | done | serialized v3.1 Session regression plus real ComfyUI journal recovery into a workflow widget |
| 108.17 Node Copy | done | public node copy forks a distinct session ID/origin lineage while retaining the stable prompt and revision |
| 108.18 Supplement Changed | done | bound supplement fingerprint mismatch tests; Model Core hash remains separate |
| 108.19 CharacterBible Changed | done | same-nonce mismatch-before-Gateway production test |
| 108.20 Storyboard Major Change | done | source fingerprint comparison; finer compatibility/rebase is not implemented |
| 108.21 Target Compatible Switch | done | lenient target changes warn and continue; strict changes require a successful new lineage |
| 108.22 Target Incompatible Switch | done | strict mode creates a replacement lineage only after successful CREATE |
| 108.23 Long Conversation | done | explicit conversation/revision caps in `test_prompt_session.py` |
| 108.24 Workflow Size | done | Session history remains capped at 10 revisions/40 messages and the serialized hidden workflow envelope is hard-capped at 4 MiB; load and pre-commit regressions prove oversized state never replaces the stable revision |
| 108.25 Prompt Injection in Storyboard | done | external context is task data, not executable instruction; prompt inventory tests |
| 108.26 Prompt Injection in Markdown Supplement | done | local Markdown is labelled `SUPPLEMENT` guidance with explicit/target/node selection; immutable Runtime/Model Core/output rules remain in system policy; hostile Markdown and public-node injection regressions cover the boundary |
| 108.27 ZIP Path Traversal | done | attachment traversal regression in `test_attachments.py` |
| 108.28 Supplement Scripts | done | only bounded UTF-8 Markdown is accepted; no YAML Skill/script loader remains |
| 108.29 Style Conflict | partial | deterministic renderer/validator checks remain; creative Critic was removed by ADR 0007 |
| 108.30 Style Identity Lock | partial | stable fact locks exist; dedicated style/identity production regression remains |

P5 durable recovery is implemented. Successful public-node commits publish an atomic,
bounded snapshot to the ComfyUI user directory; workflow load offers an explicit
recover/discard choice for a newer revision, and copied nodes fork independent lineage.
Real ComfyUI/LM Studio evidence is recorded in
`docs/prompt-architecture/p5-real-acceptance-2026-08-12.md`.

## Model Core / Markdown supplement migration

The former runtime YAML Prompt Skill registry, repository Skill files, `/skills`
routes, settings editor, and Skill-only tests were intentionally removed because
there are no user workflows to preserve. Target hard rules now have one immutable
owner in `prompting/model_cores.py`. User-authored Markdown is a separate,
lower-priority reference layer managed by `services/supplements.py`; it is stored
locally, bounded to 256 KiB, path/UTF-8/hash checked, selectable by explicit ID (or
target Studio `auto`), and included in every supported LLM node with provenance.
The migration is covered by `tests/test_supplements.py`, route CRUD smoke tests,
and production LLM/Reference/Image Studio injection tests. It does not add a new
policy language: hard behavior changes still require Model Core/code/schema/
validator changes and contract regressions.

## PH5 Operation Policy Migration

PH5 is complete. `prompting/operation_policies.py` is the only production owner
for CREATE, REFINE, FORMAT_REPAIR, PROTOCOL_RETRY, OBSERVE_TEXT, and
OBSERVE_IMAGE responsibilities. Model-specific rules remain in Model Core;
ChangeSet path syntax remains Node/Domain Core; current plans and validation
issues remain structured task data. The old Composer/H3 operation enums,
disconnected PromptSource registry, copied H3 JSON prompt builder, and unused
offline storyboard-to-H3 conversion were deleted rather than preserved as
compatibility placeholders. PH6 output-contract migration remains open.

## Known Phase Gaps Outside §108

- Both Studio nodes use their selected freeform or typed transaction lane end to end;
  neither calls an obsolete one-shot node.
- Recovery Journal is local to one ComfyUI user directory; distributed multi-host
  coordination remains outside the repository's current scope.
- Automatic fingerprint Rebase/target migration is not implemented; mismatches
  preserve the stable revision and require New Session or an existing restore.

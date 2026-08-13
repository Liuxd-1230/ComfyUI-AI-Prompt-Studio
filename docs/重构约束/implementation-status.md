# Persistent Contract Implementation Status

> **ADR 0008 current runtime:** PromptSession v3.2 and both Studio nodes use one
> complete-prompt path. The public execution-mode switch and the disconnected strict
> Plan/ChangeSet/transaction implementation were removed after real 基元/LM comparison
> showed extra latency, format failures, and H3 semantic false positives. Old lenient
> sessions migrate to the single path; old strict sessions require a new conversation.
> Historical P0-P4 rows below document completed architecture experiments, not current
> production APIs. Current acceptance is tracked by `test_single_lane_studio.py`, public
> Studio flow tests, and the prompt matrix.

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
| 108.16 Workflow Reload | done | serialized v3.2 Session regression plus real ComfyUI journal recovery into a workflow widget |
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
compatibility placeholders. Its completion preceded the PH6 unit recorded below.

## PH6 Schema Contract Cleanup

PH6 is complete. `prompting/output_contracts.py` is the production interface for
tagged prompts, JSON objects, and JSON Schema responses. The same immutable contract
now supplies the assembly source and ID, `GenerateRequest` intent, native adapter
schema, JSON mode, and a deterministic non-native fallback derived from that schema.
Reference vision calls use the same interface, including a real identity-verdict
schema. Hand-copied Reference JSON examples, target Model Core transport wording,
and caller-level `json_mode`/`output_schema` flags were removed.

## PH7 Markdown Supplemental System

PH7 is complete under the binding phase numbering. `PromptSupplement`, the safe
local registry, file import/edit/delete, global/node/target scope, enable/disable,
explicit/auto selection, per-file and active-context budgets, SHA-256 integrity,
path confinement, Settings management, and production Prompt Builder loading are
implemented. Corrupt registry state raises a visible diagnostic instead of appearing
empty. Tests import real Markdown, capture final assembly provenance, reject disabled
or wrong-scope files, enforce budgets/path/hash checks, and prove the final Output
Contract follows hostile supplemental guidance.

## PH8 Node UI Integration

PH8 is complete. LLM Generate, Reference Analyzer, Storyboard Builder, Image Prompt
Studio, and H3 Prompt Studio now share a collapsed Advanced supplement picker. It
loads the live registry, distinguishes enabled/applicable/disabled/missing records,
supports explicit multi-selection and the nodes where `auto` is safe, and reports
load failures with retry. The raw serialized STRING widget is hidden but retained as
the stable workflow compatibility field, so Markdown content never enters workflow
JSON and the primary node UI remains focused.

## PH9 Prompt Contract Regression

PH9 is complete. `scripts/verify_prompt_contracts.ps1` is the single executable release
gate for the binding checklist: full unit/integration/mock-Gateway/workflow/node-loader
pytest coverage, compilation of every production Python layer, enumeration and syntax
checking of every frontend JavaScript file, and diff whitespace validation. The durable
evidence map is `docs/prompt-architecture/ph9-prompt-contract-regression.md`. External
provider behavior changes still require a separately recorded live acceptance run;
the deterministic gate does not overclaim that boundary.

The follow-up public matrix is executable in `tests/test_acceptance_matrix.py` and
recorded in `examples/acceptance/prompt_matrix.json`. It covers every public mode and
all 35 type-compatible APS port connections. The 2026-08-13 production-node run used
the 基元 profile without downstream generation models: Image Studio 12/12, H3 Studio
10/10, LLM text/schema, and text-reference→Bible→Storyboard→Select passed.

The separate LM Studio 9B acceptance is recorded in
`docs/prompt-architecture/local-9b-multiturn-boundary-acceptance-2026-08-13.md`.
It covers production-node multi-turn CREATE/REFINE, restore/no-op, locked edits,
Reference/Storyboard/LLM public modes, and H3 media boundary classes. The lenient
Image and H3 lanes passed repeated edits; strict local-9B ChangeSets remain
provider-quality-limited but preserve stable state on rejection. JSON outputs now
receive at most one protocol-only repair before a visible warning.

## Known Phase Gaps Outside §108

- Both Studio nodes use their selected freeform or typed transaction lane end to end;
  neither calls an obsolete one-shot node.
- Recovery Journal is local to one ComfyUI user directory; distributed multi-host
  coordination remains outside the repository's current scope.
- Automatic fingerprint Rebase/target migration is not implemented; mismatches
  preserve the stable revision and require New Session or an existing restore.

# P2 Transaction and Data-Boundary Migration

> Historical implementation record. ADR 0007 keeps ChangeSet, deterministic impact
> closure, Diff Guard, locks, and CAS in strict mode, but removes the independent LLM
> approval call described below. Declared requested paths are the strict transaction's
> authority; model-proposed dependencies remain unauthorized.

## Production Transaction Path

`schemas/changeset.py` defines the reasoned mutation contract: base revision, plan
type, change category, intent scope, requested and dependent changes, invalidated
facts, constraint conflicts, and summary. Each mutation has an operation, semantic
path, typed JSON value, and reason. `services/prompt_session.request_changeset()`
is the only REFINE proposal path used by Prompt Composer and H3 Director.

The proposal does not authorize itself. A narrow deterministic gate approves only
minimal `set` operations whose semantic leaf is explicitly named in the user's own
instruction and which contain no proposed dependency, invalidation, or conflict.
All other proposals use a second compact structured call that receives
the stable plan, latest instruction, runtime constraints, and proposed ChangeSet,
then returns exact approved requested/dependent paths. The transaction rejects every
path missing from that independent intent/impact approval. Deterministic dependencies
added by Python are approved by their analyzer rather than by the proposal model.

`domain/transactions.py` gives Impact Analysis a clone, validates the returned
ChangeSet, then applies it to another clone. It rejects stale revisions, wrong plan
types, malformed/magic paths, missing or out-of-range indices, incompatible values,
locked or disallowed fields, unresolved invalidations/conflicts, and unauthorized
structural diffs. Requested changes must fall inside `intent_scope`; duplicate path
operations are rejected. A model-labelled `broad_rewrite` is accepted only when a
conservative parser also finds explicit whole-plan redesign wording in the user's
message. Normalizer changes pass through a separate Diff Guard authorization set.

Image sessions transact `{content, negative}` together. Impact Analysis removes a
matching negative token when the requested positive fact proves the conflict, while
preserving unrelated negative tokens and recording the dependent path. H3 duration
changes scale unchanged shot timestamps by the duration ratio, preserving their
relative timing and recording each dependent path. Semantic paraphrase and narrative
causality are intentionally deferred to the risk-triggered P3 critic.

H3 duration widgets, connected manifests, media-label normalization, and session
locks enter the transaction as authoritative runtime inputs; they are not applied
after Diff Guard. After the transaction, the deterministic renderer and target
validator run.
At most one targeted repair ChangeSet is attempted. `PromptSession.commit()` builds
the complete next state on an isolated copy and swaps it only after plan, prompt,
validation, revision snapshot, conversation, and timestamps all succeed. Commit also
performs a final expected-revision CAS check. Every
failure therefore preserves Current Plan, Current Prompt, and revision.

The disconnected pre-P2 Plan Patch schema/request/apply helpers were removed after
all production and tests migrated to the canonical ChangeSet transaction.

## Live Prompt Boundary Migration

All creative calls now attach a `PromptAssemblyReport` to `GenerateRequest`; direct vision calls return the same report to their caller.

- LLM Generate keeps user system instructions in the supplemental system layer, while `context` is a labelled user-role task-data block.
- Reference Analyzer separates analysis/identity policy from text anchors, Character Bible data, image slots, and images. Vision requests now use an actual system message plus user multimodal data.
- Storyboard Builder sends story, limits, CharacterBook, and ReferenceManifest as structured data. Its live request no longer copies the JSON Schema into prose.
- Prompt Studio sends prompt, book, references, Markdown supplement references, and validation issues as distinct task-data blocks; no runtime Skill is loaded or treated as a policy source.
- H3 Studio separates immutable Model Core, Operation Policy, and typed request data. Live create/retry no longer use a hand-copied JSON template.
- Persistent session refinement uses the same assembly boundary and the canonical `semantic-changeset.schema@2` contract.

PH5 removed the disconnected `build_plan_prompt()` and `h3_system_prompt()`
compatibility helpers after proving that production uses structured H3 task data,
Model Core, Operation Policy, and `H3_SCHEMA`. `build_storyboard_prompt()` remains a
model-neutral service helper with live callers.

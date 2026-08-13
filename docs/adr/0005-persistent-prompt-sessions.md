# Persistent Prompt Sessions Use Workflow-Serialized Structured State

> **2026-08-11 amendment:** ADR 0007 supersedes the mandatory single structured
> execution path and v2 migration behavior. This document remains the lineage and
> atomic-commit foundation for the strict lane; the default lenient lane persists a
> prompt payload in PromptSession v3.2 without requiring a semantic Plan.

Prompt Composer and MiniMax H3 Director use `PromptSession` as the current-state fact source. Conversation explains why revisions changed; it is not replayed to reconstruct the current prompt.

## Decision

The backend owns one deep module at the session seam:

```text
current structured plan + latest instruction
→ reasoned ChangeSet
→ Impact Analysis + clone apply + Diff Guard
→ Renderer
→ Validator
→ at most one targeted repair ChangeSet
→ atomic revision commit
```

`PromptSession` v3.2 stores target family/variant, current plan and prompt, validation,
locked constraints, the last processed message nonce, target/source/model/Model Core and Markdown supplement
fingerprints, bounded conversation messages, and the latest ten synchronized
plan/prompt revisions. A ChangeSet declares `base_revision`; stale updates, illegal
paths, list overflows, immutable fields, and locked paths are rejected before a copy
is committed. Failed calls never mutate the previous valid state.

Each `PromptRevision` is an append-only snapshot with a stable ID, parent and base
revision, change-path provenance, renderer signature and the fingerprints used for
that result. Restoring an older revision creates a new revision whose parent points
to the selected snapshot; it never pops or rewrites later history.

The ChangeSet separates requested changes, dependent changes, invalidated facts,
and constraint conflicts. Image sessions analyze positive content and negative text
together; H3 sessions analyze their typed audiovisual plan. The final session state
is built on a copy and swapped only after every revision field succeeds and the
expected revision still matches. Broad replacement additionally requires explicit
whole-plan redesign wording in the user's latest instruction.

Provider protocol failure is not a semantic commit. H3 CREATE Plan and REFINE
ChangeSet parsing may perform one bounded retry using only the concrete validation
errors and a sanitized, truncated previous response as untrusted task data. Both
attempts operate before commit; failure logs a bounded raw excerpt and returns an
actionable error while the stable plan, prompt, and revision remain unchanged.

Legacy v1 sessions preserve their last valid Plan/prompt/revisions but enter an
explicit `legacy_unbound` fingerprint state. They may recognize the final repeated
message as a no-op, but cannot accept a new refinement until the user starts a new
Session. The compatibility-only `continue_previous` widget never resets or binds a
Session; lifecycle reset requires `session_action=new`. Selecting that action does
not erase the serialized stable Session: the frontend replaces it only after the
new CREATE has succeeded. Bound sessions compare fingerprints before empty/repeated
message early returns, so a zero-call Queue cannot hide changed authoritative input.

A separate compact intent/impact call audits the proposed ChangeSet and returns exact
approved requested/dependent paths. Proposal paths are not mutation authority until
this approval succeeds; Python-proven dependencies are recorded by deterministic
Impact Analysis instead.

The session is not held on a Python node instance. The node returns the latest serialized session through ComfyUI's `ui/result` envelope. `web/prompt_studio.js` writes that JSON into the node's hidden, serializable `prompt_session` widget and marks the workflow dirty. Queue #2 therefore receives Queue #1's plan, and saving/reopening the workflow restores the same state.

P5 binds every serialized Session to ComfyUI's hidden `UNIQUE_ID`. Copying a node
forks a new session ID and records the source in `origin_session_id`, preserving the
stable prompt and revision without sharing future writes. Before swapping the stable
Session, commit publishes an atomic snapshot to a bounded durable Recovery Journal
keyed by `(session_id, node_instance_id)`. A second adapter rereads the file before
every write and rejects stale `base_revision` values. On workflow load, the frontend
offers an explicit recover/discard choice only when the journal revision is newer;
accepting recovery writes the snapshot into the widget and requires the workflow to
be saved.

The frontend displays conversation, revision, and the exact `current_prompt`; it does not apply patches or validate plans. It writes a new `message_nonce` when the user edits the message. An empty message or an already processed nonce re-renders the stable output with zero LLM calls and no revision. `operation` remains serialized for old workflows but is hidden in the new UI. New work automatically selects CREATE when no valid plan exists and REFINE otherwise.

ANIMA retains its target-specific semantic plan. Prose-oriented Z-Image, Qwen Image Edit, and Generic targets retain normalized semantic clauses, so a refinement replaces an individual clause instead of an opaque full prompt string. An explicit `broad_rewrite` may authorize a larger set of semantic paths, but session metadata, renderer controls, and locked fields remain outside mutation authority.

## Trade-offs

Workflow JSON grows with up to ten revisions and forty chat messages. The recovery
journal adds at most 100 most-recent node/session snapshots under the ComfyUI user
directory. Its process-local path lock and fresh-read CAS cover concurrent adapters in
one ComfyUI process; the atomic replace prevents partial files after a crash. It is a
local recovery mechanism, not a distributed multi-host database.

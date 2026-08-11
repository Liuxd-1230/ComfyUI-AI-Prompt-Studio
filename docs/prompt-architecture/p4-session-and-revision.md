# P4 Session and Revision

## Versioned Session Envelope

`PromptSession` is now schema version `3.0` and carries `execution_mode` plus an
explicit `freeform` or `structured` payload kind. Both modes share atomic commit,
nonce, validation, bounded history, restore, transaction identity, and Recovery
Journal seams. A freeform revision requires a non-empty prompt but no semantic Plan;
a structured revision requires both.

ADR 0007 intentionally does not migrate v1/v2 state into editable v3 state. Loading
either legacy envelope creates a new empty lenient Session with a new ID. This avoids
silently treating a previously structured lineage as freeform or rebinding old
fingerprints to current inputs. Unknown future versions and malformed v3 revisions
remain hard schema errors.

## Immutable Revision Lineage

Every successful commit creates a fresh `PromptRevision` containing `revision_id`,
`parent_revision`, `base_revision`, Plan/prompt snapshots, validation, user message,
requested/dependent/invalidated paths, renderer signature, and Model Core, Skill and
source hashes. V3 adds execution mode, payload kind, and observed context changes.
P4.1 also records `transaction_id` and the actual bounded
`repair_count`/`repair_attempted`. Its fields and nested mapping/list snapshots are frozen after
construction; Plan and validation inputs are deep-copied before the atomic swap.
History is bounded to 10 revisions and chat display to 40 messages.

Restore never removes history. The legacy `previous` action resolves the preceding
snapshot and commits it as a new revision whose parent points to the restored version.
The stored rendered prompt plus renderer signature retain the distinction needed for
future semantic restore versus exact replay.

## Message and Context Identity

Composer and H3 append a serialized `message_nonce` widget. The workbench assigns a
new nonce when the user edits the message. Re-queueing an empty message or an already
processed nonce returns the current outputs without Gateway calls or a new revision;
legacy workflows without the widget use a deterministic message hash.

Each successful transaction pins target, actual renderer/validator Model Core,
active Skill, Character Bible/Book, Storyboard and Reference Manifest hashes. A
connected H3 image/video/audio payload is hashed as content, not merely by slot or
count. Bound sessions compare these fingerprints on every Queue, including an empty
or repeated message, before taking the zero-call path. A changed authoritative
context is reported before Gateway or commit and leaves the stable revision
untouched. The old `continue_previous` widget remains
serialized only for workflow compatibility and has no lifecycle authority; reset is
the explicit `session_action=new`. The workbench does not clear the serialized old
Session when this button is clicked; only a successful backend CREATE replaces it.
Rebase and target migration remain explicit
later-phase operations rather than being disguised as chat refinement.

## Recovery Journal Seam

`PromptSession.commit()` may publish its fully staged next state through a
`RecoveryJournal` before swapping the stable in-memory Session. Journal entries are
keyed by Session and node instance and carry transaction/base/result revision IDs;
stale branches are rejected. A journal write failure leaves the stable Session
byte-for-byte unchanged. `MemoryRecoveryJournal` proves this contract but is not a
durable workflow backend. Durable crash recovery and frontend writeback remain P5.

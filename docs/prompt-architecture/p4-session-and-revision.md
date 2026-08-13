# P4 Session and Revision

## Versioned Session Envelope

`PromptSession` is schema version `3.2` and carries `execution_mode` plus an
explicit `freeform` or `structured` payload kind. Both modes share atomic commit,
nonce, validation, bounded history, restore, transaction identity, and Recovery
Journal seams. A freeform revision requires a non-empty prompt but no semantic Plan;
a structured revision requires both.

Prompt Studio accepts only the current v3.2 Session envelope. Older, missing, future,
or malformed versions are hard schema errors and never become editable state. This
avoids silently treating an incompatible lineage as freeform or rebinding unknown
fingerprints to current inputs.

## Immutable Revision Lineage

Every successful commit creates a fresh `PromptRevision` containing `revision_id`,
`parent_revision`, `base_revision`, Plan/prompt snapshots, validation, user message,
requested/dependent/invalidated paths, renderer signature, and Model Core, Markdown supplement and
source hashes. V3 adds execution mode, payload kind, and observed context changes.
P4.1 also records `transaction_id` and the actual bounded
`repair_count`/`repair_attempted`. Its fields and nested mapping/list snapshots are frozen after
construction; Plan and validation inputs are deep-copied before the atomic swap.
History is bounded to 10 revisions and chat display to 40 messages. The serialized
hidden workflow envelope is additionally capped at 4 MiB; oversized state is rejected
before the stable Session or Recovery Journal is changed.

Restore never removes history. The `previous` action resolves the preceding
snapshot and commits it as a new revision whose parent points to the restored version.
The stored rendered prompt plus renderer signature retain the distinction needed for
future semantic restore versus exact replay.

## Message and Context Identity

Composer and H3 append a serialized `message_nonce` widget. The workbench assigns a
new nonce when the user edits the message. Re-queueing an empty message or an already
processed nonce returns the current outputs without Gateway calls or a new revision;
an empty nonce uses a deterministic idempotency hash so backend callers remain safe.

Each successful transaction pins target, actual renderer/validator Model Core,
active Markdown supplement, Character Bible/Book, Storyboard and Reference Manifest hashes. A
connected H3 image/video/audio payload is hashed as content, not merely by slot or
count. Bound sessions compare these fingerprints on every Queue, including an empty
or repeated message, before taking the zero-call path. A changed authoritative
context is reported before Gateway or commit and leaves the stable revision
untouched. Reset is the explicit `session_action=new`. The workbench does not clear the serialized
Session when this button is clicked; only a successful backend CREATE replaces it.
Rebase and target migration remain explicit
later-phase operations rather than being disguised as chat refinement.

## Recovery Journal Seam

`PromptSession.commit()` publishes its fully staged next state through a
`RecoveryJournal` before swapping the stable in-memory Session. Journal entries are
keyed by Session and node instance and carry transaction/base/result revision IDs;
stale branches are rejected. A journal write failure leaves the stable Session
byte-for-byte unchanged; the durable ComfyUI user-directory adapter and frontend
writeback are covered by the P5 real acceptance record.

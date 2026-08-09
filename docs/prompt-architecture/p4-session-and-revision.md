# P4 Session and Revision

## Versioned Session Envelope

`PromptSession` remains the compatibility name used by existing workflows, but its
serialized envelope is now schema version `2.0`. Loading a v1 workflow migrates each
stored snapshot to a stable revision identity and preserves the active Plan, prompt,
validation and revision number. Unknown future Session versions and malformed
revision entries are rejected instead of silently dropping authoritative state. The
v2 state records the last processed message ID
and a typed `SessionFingerprints` block.

A migrated v1 Session cannot reconstruct the target/source/Skill fingerprints that
did not exist in the old workflow. It is therefore marked `legacy_unbound`: an exact
repeat of its last user message remains a zero-call no-op, while any new instruction
is rejected until the user explicitly starts a new Session. It is never silently
bound to whichever inputs happen to be connected at migration time.

## Immutable Revision Lineage

Every successful commit creates a fresh `PromptRevision` containing `revision_id`,
`parent_revision`, `base_revision`, Plan/prompt snapshots, validation, user message,
requested/dependent/invalidated paths, renderer signature, and Model Core, Skill and
source hashes. Its fields and nested mapping/list snapshots are frozen after
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

# Persistent Prompt Sessions Use Workflow-Serialized Structured State

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

`PromptSession` stores target family/variant, current plan and prompt, validation, locked constraints, short conversation messages, and the latest five synchronized plan/prompt revisions. A ChangeSet declares `base_revision`; stale updates, illegal paths, list overflows, immutable fields, and locked paths are rejected before a copy is committed. Failed calls never mutate the previous valid state.

The ChangeSet separates requested changes, dependent changes, invalidated facts,
and constraint conflicts. Image sessions analyze positive content and negative text
together; H3 sessions analyze their typed audiovisual plan. The final session state
is built on a copy and swapped only after every revision field succeeds and the
expected revision still matches. Broad replacement additionally requires explicit
whole-plan redesign wording in the user's latest instruction.

A separate compact intent/impact call audits the proposed ChangeSet and returns exact
approved requested/dependent paths. Proposal paths are not mutation authority until
this approval succeeds; Python-proven dependencies are recorded by deterministic
Impact Analysis instead.

The session is not held on a Python node instance. The node returns the latest serialized session through ComfyUI's `ui/result` envelope. `web/prompt_studio.js` writes that JSON into the node's hidden, serializable `prompt_session` widget. Queue #2 therefore receives Queue #1's plan, and saving/reopening the workflow restores the same state.

The frontend displays conversation, revision, and the exact `current_prompt`; it does not apply patches or validate plans. `operation` remains serialized for old workflows but is hidden in the new UI. New work automatically selects CREATE when no valid plan exists and REFINE otherwise.

ANIMA retains its target-specific semantic plan. Prose-oriented Z-Image, Qwen Image Edit, and Generic targets retain normalized semantic clauses, so a refinement replaces an individual clause instead of an opaque full prompt string. An explicit `broad_rewrite` may authorize a larger set of semantic paths, but session metadata, renderer controls, and locked fields remain outside mutation authority.

## Trade-offs

Workflow JSON grows with up to five revisions. Concurrent updates are guarded by `base_revision`; ComfyUI normally executes queued prompts serially, but separate clients editing the same workflow file still require user coordination. Full branching and a visual diff browser remain future work.

# Persistent Prompt Sessions Use Workflow-Serialized Structured State

Prompt Composer and MiniMax H3 Director use `PromptSession` as the current-state fact source. Conversation explains why revisions changed; it is not replayed to reconstruct the current prompt.

## Decision

The backend owns one deep module at the session seam:

```text
current structured plan + latest instruction
→ validated Plan Patch
→ deterministic apply
→ Renderer
→ Validator
→ at most one semantic repair
→ atomic revision commit
```

`PromptSession` stores target family/variant, current plan and prompt, validation, locked constraints, short conversation messages, and the latest five synchronized plan/prompt revisions. A patch declares `base_revision`; stale updates, illegal paths, list overflows, immutable fields, and locked paths are rejected before a copy is committed. Failed calls never mutate the previous valid state.

The session is not held on a Python node instance. The node returns the latest serialized session through ComfyUI's `ui/result` envelope. `web/prompt_studio.js` writes that JSON into the node's hidden, serializable `prompt_session` widget. Queue #2 therefore receives Queue #1's plan, and saving/reopening the workflow restores the same state.

The frontend displays conversation, revision, and the exact `current_prompt`; it does not apply patches or validate plans. `operation` remains serialized for old workflows but is hidden in the new UI. New work automatically selects CREATE when no valid plan exists and REFINE otherwise.

ANIMA retains its target-specific semantic plan. Prose-oriented Z-Image, Qwen Image Edit, and Generic targets retain normalized semantic clauses, so a refinement replaces an individual clause instead of an opaque full prompt string. Broad rebuilds may replace only the renderer-owned root and preserve the surrounding session bundle and locked fields.

## Trade-offs

Workflow JSON grows with up to five revisions. Concurrent updates are guarded by `base_revision`; ComfyUI normally executes queued prompts serially, but separate clients editing the same workflow file still require user coordination. Full branching and a visual diff browser remain future work.

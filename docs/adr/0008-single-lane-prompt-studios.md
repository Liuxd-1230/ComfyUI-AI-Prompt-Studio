# ADR 0008: Single-Lane Prompt Studios

## Status

Accepted on 2026-08-13. This supersedes ADR 0007's dual-lane runtime decision.

## Decision

Image Prompt Studio and MiniMax H3 Prompt Studio expose one execution path that
stores the complete downstream prompt as the current Session fact. CREATE and REFINE
use the same lightweight output contract. A second model call is allowed only when the
first result is protocol garbage or fails a deterministic hard check; that retry receives
the rejected output and concrete issues and must preserve content.

The public `execution_mode` input, structured Studio Plan/ChangeSet transaction path,
Diff Guard, and their disconnected production helpers are removed. Old `lenient`
sessions migrate to schema 3.2 and the single path. Old `strict` sessions cannot be
converted without inventing state, so loading them raises a clear “start new session”
error. This is acceptable because the extension has no released strict workflows.

## Retained Guarantees

- Session revisions commit atomically and previous successful prompts remain recoverable.
- Source/model/target fingerprints and copied-node lineage remain explicit.
- ANIMA output is English, receives the target quality prefix and base negative prompt,
  and preserves connected identity anchors and explicit user exclusions.
- H3 output retains official mode format, duration/media limits, identity anchors,
  timestamps, camera terminology, references, and sound checks.
- Structured JSON modes in LLM, Reference, and Storyboard nodes are unaffected.

## Consequences

Local models no longer spend calls producing and patching a second semantic
representation whose validator could report a false success while losing source facts.
The only editable truth is the prompt the user sees and sends downstream. Historical
dual-lane acceptance reports remain evidence, not current usage guidance.

# ADR 0007: Prompt Studios Use Lenient and Strict Execution Lanes

- Status: Accepted
- Date: 2026-08-11
- Supersedes: the single mandatory structured transaction path in ADR 0005/0006

## Context

The P1–P4 implementation made structured Plans, ChangeSets, independent intent
approval, semantic criticism, repair, fingerprints, and revision CAS mandatory for
every persistent edit. Those controls protect state, but local 7B–14B OpenAI-
compatible models frequently fail one of the nested JSON protocols. A technically
correct guard then becomes a user-visible availability failure. Treating malformed
JSON as a prompt is also unsafe because a partial object or schema explanation is
neither valid state nor a usable target prompt.

The product promise is therefore split. Lenient mode favors usable prompt iteration
with deterministic hard checks. Strict mode favors structured mutation and atomic
state. Neither mode claims perfect natural-language intent understanding.

## Decision

Replace `APS_PromptComposer` and `APS_MiniMaxH3Director` with
`APS_PromptStudio` and `APS_H3PromptStudio`. Both expose
`execution_mode = lenient | strict`, defaulting to `lenient`, and infer CREATE versus
REFINE only from Session state. Legacy operation dropdowns and compatibility
branches are removed; existing workflows are intentionally not migrated because the
only current user accepted the break.

### Lenient lane

The model receives explicit output instructions:

```text
<PROMPT>
complete target prompt
</PROMPT>
<SUMMARY>
short change summary
</SUMMARY>
```

The parser accepts a complete tagged prompt. It may also accept untagged text only
when deterministic classification identifies a normal prompt rather than JSON-like
or protocol explanatory output; this produces a visible warning. Fenced output,
obvious surrounding prose, and simple tag defects are cleaned deterministically.
Protocol garbage receives at most one content-preserving format repair request.
Failure never commits.

REFINE sends only the current prompt, latest instruction, and current connected
context—not the full conversation. Source/Skill/target changes are recorded and
shown as warnings but do not block. Python enforces only provable target rules:
non-empty output, reference existence, positive/negative contradictions, H3 media
and timing limits, and ANIMA English visual prose. ANIMA permits non-English names,
proper nouns, reference labels, and quoted on-screen text. No semantic Critic or
creative auto-repair runs in this lane.

### Strict lane

Strict mode retains typed Plan, reasoned ChangeSet, deterministic dependency
analysis, Diff Guard, hard locks, target renderer/validator, revision CAS, and atomic
commit. It removes the routine independent authorization call and LLM Semantic
Critic. The declared ChangeSet is mutation authority; strict means structural and
transactional safety, not perfect grounding of natural-language intent. Only one
content-preserving protocol repair is automatic. Semantic errors are reported to the
user and are not creatively repaired in the background.

### Session and mode changes

`PromptSession v3` is one envelope with an explicit execution mode. Revisions carry
either a freeform prompt payload or a structured Plan payload and retain the latest
ten successful versions. A failed execution does not consume its message nonce, so
the user may Queue the same strict request again. Restore creates a new revision.

Changing mode starts a new lineage on the next successful CREATE. Until that CREATE
succeeds, the previous Session remains intact; after success its old lineage is
discarded. Existing v1/v2 sessions are not migrated into an editable v3 Session:
the next execution starts from the node's current text.

The frontend displays yellow warnings for accepted untagged prompts and changed
context. It never applies semantic changes. Both Studio nodes keep only target-ready
prompt outputs, validation, change summary, and serialized Session; internal Plans
remain inside strict Session state rather than public node ports.

## Consequences

Normal lenient CREATE/REFINE uses one model call. A malformed protocol can use one
additional repair call. Strict normal operation likewise uses one Plan/ChangeSet
call and at most one protocol repair. There is no automatic strict-to-lenient
fallback.

Lenient mode cannot guarantee that a model preserved every unmentioned semantic
fact. Strict mode guarantees declared-diff and commit integrity but does not claim
that the model's declared intent scope is a perfect interpretation of the user.
These limitations must be visible in help and validation text.

Completion requires unit and production-path tests plus a real ComfyUI/LM Studio
prompt-only run: lenient CREATE and two REFINE rounds, untagged prompt, partial
JSON/tag failures, strict CREATE/REFINE, mode switch, and restore. The same loaded
LLM may be reused; no image/video generation or unload step is required.

# Prompt Inventory

This inventory is the P0 baseline for every path that can send instructions or task data to a model. A new model call is incomplete until it is added here and assigned an owner in `prompt-ownership.md`.

## Creative and Analysis Calls

| ID | Caller | Purpose | System sources | User/task-data sources | Structured contract | Transport |
|---|---|---|---|---|---|---|
| `llm.generate` | `nodes/llm_chat.py` | General conversation | internal safety boundary; user `system_prompt`; JSON fallback | history, `user_prompt`, `context`, attachments | optional user JSON Schema | `Gateway.generate` |
| `reference.text` | `nodes/reference_analyzer.py` | Extract text-anchor traits | extraction role | mode prompt, CharacterBook, text anchor | `CANDIDATE_SCHEMA` | `Gateway.generate` |
| `reference.image` | `nodes/reference_analyzer.py` | Extract traits from each image | none at caller | mode prompt, CharacterBook, image | prompt-described JSON | `VisionService.call_vision` |
| `reference.identity` | `nodes/reference_analyzer.py` | Decide whether images share identity | none at caller | `IDENTITY_COMPARISON_PROMPT`, images | prompt-described JSON | `VisionService.call_vision` |
| `storyboard.create` | `nodes/storyboard_builder.py` | Build model-neutral storyboard | storyboard role | split/style constraints, CharacterBook/Bible, manifest, story | `STORYBOARD_SCHEMA` | `Gateway.generate` |
| `composer.render` | `nodes/prompt_composer.py` | Generate/expand/rewrite/translate/repair image prompts | selected Skill; transitional create policy | prompt, book, references, repair issues | family-specific JSON | `Gateway.generate` |
| `session.changeset` | `services/prompt_session.py` | Canonical semantic REFINE proposal | minimum-consistent-change policy | editable semantic plan, locked paths, latest request, revision | `CHANGESET_SCHEMA` | injected `Gateway.generate` |
| `session.impact` | `services/prompt_session.py` | Independently approve requested/dependent paths | intent grounding + impact approval policy | current semantic plan, latest request, runtime constraints, proposed ChangeSet | `CHANGE_AUTHORIZATION_SCHEMA` | same Gateway transport, separate structured call |
| `semantic.critic` | `domain/gateway_critic.py` | Audit only high-risk transaction candidates | semantic consistency policy; anti-realism-policing boundary | affected before/after slice, adjacent shots, proposed ChangeSet, locked values | `CRITIC_SCHEMA` | injected `Gateway.generate`; never mutates Plan |
| `session.patch-compat` | `services/prompt_session.py` | Deprecated direct-call compatibility for pre-P2 callers | legacy `REFINE_POLICY` | legacy persisted bundle | `PATCH_SCHEMA` | injected `Gateway.generate`; not used by nodes |
| `h3.create` | `nodes/minimax_h3_director.py` | Build H3 audiovisual plan | H3 protocol + editable planning strategy + transitional policy | mode, duration, storyboard, books, manifest, user text | `H3_SCHEMA` | `Gateway.generate` |
| `h3.repair` | `nodes/minimax_h3_director.py` | Repair reported H3 violations once | H3 protocol + repair policy | current plan and validation issues | `H3_SCHEMA` | `Gateway.generate` |

## Operational Probes and Protocol Mutation

`services/capability_probe.py` makes active Chat Completions, Responses, JSON, tool, vision, file, and web-search probes. These are operational tests rather than creative generation, but their probe prompts remain versioned product behavior and must not be reused as model guidance.

`services/gateway.py`, `services/adapters/chat_adapter.py`, and `services/adapters/responses_adapter.py` may add schema fallbacks, untrusted-search guards, tool results, and attachment content. They own protocol encoding only. They must not acquire target-model prompting rules.

## Remaining Compatibility Boundaries

- `request_plan_patch()` remains importable for pre-P2 direct callers, but no production node invokes it; new work must use `request_changeset()`.
- `services/h3_plan.py` and `skills/minimax_h3/director.yaml` still state overlapping H3 protocol guidance; the Model Core migration must leave one immutable owner.
- ANIMA model rules and operation behavior are mixed across `skills/anima_*.yaml`, `renderers/anima.py`, and validators.
- Some legacy Skill files still combine Model Core and operation policy in one `system_prompt`.

## Inventory Gate

The static contract test `tests/test_prompt_architecture_inventory.py` compares known generation and vision call sites with the IDs above. Intentional additions require updating the inventory, ownership map, assembly contract tests, and migration status together.

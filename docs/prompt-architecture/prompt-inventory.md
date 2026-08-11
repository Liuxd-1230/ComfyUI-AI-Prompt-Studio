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
| `studio.image` | `nodes/prompt_studio.py` | Own all image Studio model calls across the two lanes | lightweight/strict runtime boundary plus target and operation policies | latest instruction, current prompt or Plan, and current connected sources | lenient envelope, strict Plan, or ChangeSet | `Gateway.generate` |
| `studio.image.lenient` | `nodes/prompt_studio.py` | Create/refine one complete image prompt | lightweight envelope + target policy + create/refine policy | latest instruction, current prompt, current connected sources | `<PROMPT>/<SUMMARY>` | `Gateway.generate` |
| `studio.image.repair` | `nodes/prompt_studio.py` | One content-preserving lenient protocol repair | envelope + target policy + format-repair policy | rejected output and concrete deterministic issues | `<PROMPT>/<SUMMARY>` | `Gateway.generate` |
| `studio.image.strict-create` | `nodes/prompt_studio.py` | Create typed image semantic state | strict state boundary + target policy | latest instruction and current connected sources | family-specific `ImageSemanticPlan` schema | `Gateway.generate` |
| `studio.h3` | `nodes/h3_prompt_studio.py` | Own all H3 Studio model calls across both lanes | lightweight/strict boundary plus official H3 core | latest instruction, current prompt or Plan, storyboard, identities, media manifest | lenient envelope, `H3_SCHEMA`, or ChangeSet | `Gateway.generate` |
| `studio.h3.lenient` | `nodes/h3_prompt_studio.py` | Create/refine complete rendered H3 text | envelope + H3 target policy | latest instruction, current prompt, current connected sources | `<PROMPT>/<SUMMARY>` | `Gateway.generate` |
| `studio.h3.strict-create` | `nodes/h3_prompt_studio.py` | Create typed H3 semantic state | official H3 core + strict create policy | typed H3 task data | `H3_SCHEMA` | `Gateway.generate` |
| `session.changeset` | `services/prompt_session.py` | Canonical semantic REFINE proposal | minimum-consistent-change policy | editable semantic plan, locked paths, latest request, revision | `CHANGESET_SCHEMA` | injected `Gateway.generate` |

## Operational Probes and Protocol Mutation

`services/capability_probe.py` makes active Chat Completions, Responses, JSON, tool, vision, file, and web-search probes. These are operational tests rather than creative generation, but their probe prompts remain versioned product behavior and must not be reused as model guidance.

`services/gateway.py`, `services/adapters/chat_adapter.py`, and `services/adapters/responses_adapter.py` may add schema fallbacks, untrusted-search guards, tool results, and attachment content. They own protocol encoding only. They must not acquire target-model prompting rules.

## Remaining Transition Boundaries

- `services/h3_plan.py` and `skills/minimax_h3/director.yaml` still state overlapping H3 protocol guidance; the Model Core migration must leave one immutable owner.
- ANIMA model rules and operation behavior are mixed across `skills/anima_*.yaml`, `renderers/anima.py`, and validators.
- Some legacy Skill files still combine Model Core and operation policy in one `system_prompt`.

## Inventory Gate

The static contract test `tests/test_prompt_architecture_inventory.py` compares known generation and vision call sites with the IDs above. Intentional additions require updating the inventory, ownership map, assembly contract tests, and migration status together.

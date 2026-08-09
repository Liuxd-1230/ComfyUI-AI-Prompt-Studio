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
| `session.refine` | `services/prompt_session.py` | Transitional persisted-plan patch | `REFINE_POLICY` | current plan, locked paths, latest request | `PATCH_SCHEMA` | injected `Gateway.generate` |
| `h3.create` | `nodes/minimax_h3_director.py` | Build H3 audiovisual plan | H3 protocol + editable planning strategy + transitional policy | mode, duration, storyboard, books, manifest, user text | `H3_SCHEMA` | `Gateway.generate` |
| `h3.repair` | `nodes/minimax_h3_director.py` | Repair reported H3 violations once | H3 protocol + repair policy | current plan and validation issues | `H3_SCHEMA` | `Gateway.generate` |

## Operational Probes and Protocol Mutation

`services/capability_probe.py` makes active Chat Completions, Responses, JSON, tool, vision, file, and web-search probes. These are operational tests rather than creative generation, but their probe prompts remain versioned product behavior and must not be reused as model guidance.

`services/gateway.py`, `services/adapters/chat_adapter.py`, and `services/adapters/responses_adapter.py` may add schema fallbacks, untrusted-search guards, tool results, and attachment content. They own protocol encoding only. They must not acquire target-model prompting rules.

## Current Duplication and Boundary Violations

- `nodes/llm_chat.py` currently copies `context` into the system message. P2 must keep it as labelled, untrusted task data.
- `services/storyboard.py` repeats the complete JSON shape even when `STORYBOARD_SCHEMA` is sent. P2 must reduce the prose to semantic constraints and derive any fallback from the schema contract.
- `services/h3_plan.py` and `skills/minimax_h3/director.yaml` both state H3 protocol rules. P1 separates immutable Model Core from editable operation guidance.
- ANIMA model rules and operation behavior are mixed across `skills/anima_*.yaml`, `renderers/anima.py`, and validators.
- Legacy Skill files currently combine Model Core, operation policy, data-boundary warnings, and output instructions in one `system_prompt`.

## Inventory Gate

The static contract test `tests/test_prompt_architecture_inventory.py` compares known generation and vision call sites with the IDs above. Intentional additions require updating the inventory, ownership map, assembly contract tests, and migration status together.

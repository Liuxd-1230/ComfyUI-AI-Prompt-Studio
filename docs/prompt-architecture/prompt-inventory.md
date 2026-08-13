# Prompt Inventory

This inventory is the P0 baseline for every path that can send instructions or task data to a model. A new model call is incomplete until it is added here and assigned an owner in `prompt-ownership.md`.

## Creative and Analysis Calls

| ID | Caller | Purpose | System sources | User/task-data sources | Structured contract | Transport |
|---|---|---|---|---|---|---|
| `llm.generate` | `nodes/llm_chat.py` | General conversation | internal safety boundary; user `system_prompt`; JSON fallback | history, `user_prompt`, `context`, attachments | optional user JSON Schema | `Gateway.generate`; JSON/Schema output gets at most one `FORMAT_REPAIR` Gateway call before a visible warning |
| `reference.text` | `nodes/reference_analyzer.py` | Extract text-anchor traits | extraction role | mode prompt, CharacterBook, text anchor | `CANDIDATE_SCHEMA` | `Gateway.generate` |
| `reference.image` | `nodes/reference_analyzer.py` | Extract traits from each image | analysis guard + mode semantics | CharacterBook, image | `reference-candidate` OutputContract | `VisionService.call_vision` |
| `reference.identity` | `nodes/reference_analyzer.py` | Decide whether images share identity | identity evidence policy | images | `identity-verdict` OutputContract | `VisionService.call_vision` |
| `storyboard.create` | `nodes/storyboard_builder.py` | Build model-neutral storyboard | storyboard role | split/style constraints, CharacterBook/Bible, manifest, story | `STORYBOARD_SCHEMA` | `Gateway.generate` |
| `studio.image` | `nodes/prompt_studio.py` | Own image Studio create/refine and its single repair attempt | lightweight runtime boundary plus target and operation policies | latest instruction, current prompt, current connected sources | `<PROMPT>/<SUMMARY>` | `Gateway.generate` |
| `studio.image.repair` | `nodes/prompt_studio.py` | One content-preserving format or hard-rule repair | target policy + concrete validator issues | rejected output and exact issues | `<PROMPT>/<SUMMARY>` | `Gateway.generate` |
| `studio.h3` | `nodes/h3_prompt_studio.py` | Own H3 Studio create/refine and its single repair attempt | official H3 core and mode policy | latest instruction, current prompt, storyboard, identities, media manifest | `<PROMPT>/<SUMMARY>` | `Gateway.generate` |
| `studio.h3.repair` | `nodes/h3_prompt_studio.py` | One content-preserving H3 format or hard-rule repair | H3 target policy + concrete validator issues | rejected output and exact issues | `<PROMPT>/<SUMMARY>` | `Gateway.generate` |

## Operational Probes and Protocol Mutation

`services/capability_probe.py` makes active Chat Completions, Responses, JSON, tool, vision, file, and web-search probes. These are operational tests rather than creative generation, but their probe prompts remain versioned product behavior and must not be reused as model guidance.

`prompting/output_contracts.py` owns response shape and derived schema fallback.
`services/gateway.py` and the adapters only select/encode the active provider protocol;
they must not acquire target-model prompting rules or hand-authored schemas.

## Model Core and supplement boundary

- Target hard rules live in `prompting/model_cores.py`; `services/h3_plan.py` is a compatibility schema/task-data helper, not a second editable policy owner.
- User-authored Markdown is selected through `services/supplements.py` and enters as `SUPPLEMENT` guidance with provenance. It never owns transport, schema, validation, locks, or semantic facts.
- New target rules must update the Model Core, renderer/validator contract, inventory, and tests together. Do not add a YAML Skill compatibility path.

## Inventory Gate

The static contract test `tests/test_prompt_architecture_inventory.py` compares known generation and vision call sites with the IDs above. Intentional additions require updating the inventory, ownership map, assembly contract tests, and migration status together.

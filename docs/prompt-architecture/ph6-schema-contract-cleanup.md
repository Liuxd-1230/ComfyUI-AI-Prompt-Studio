# PH6 Schema Contract Cleanup

PH6 makes the output contract a machine-owned fact instead of a collection of
loosely related flags and prompt strings.

## Interface

`OutputContract` owns:

- a versioned identifier recorded in `PromptAssemblyReport`;
- the final `OUTPUT_CONTRACT` system source;
- an optional immutable JSON Schema;
- whether JSON mode is required;
- deterministic fallback guidance derived from the same schema.

Callers pass one contract to Prompt Assembly and `GenerateRequest`. Gateway selects
native Structured Output when the active protocol was probed successfully. Otherwise
it derives a compact JSON constraint from that same contract without mutating the
original request, so a Responses-to-Chat fallback is recalculated correctly.

## Migrated paths

Image and H3 Studio, Storyboard Builder, Reference Analyzer text/vision paths,
identity comparison, semantic ChangeSet, and general LLM JSON modes use this seam.
The lenient Studio envelope is also an `OutputContract`, not Runtime Policy prose.

Reference mode prompts now describe analysis semantics only. Their former copied
JSON examples were deleted. H3 Model Core likewise no longer commands a transport
shape. Supplemental Markdown is ordered below the final Output Contract and cannot
replace it.

## Acceptance evidence

Tests exercise the interface, native-schema and non-native fallback adapters,
protocol switching, public nodes, and vision assembly. A static gate rejects
caller-level `output_schema`, `json_mode`, and free-form `output_contract_id` usage.

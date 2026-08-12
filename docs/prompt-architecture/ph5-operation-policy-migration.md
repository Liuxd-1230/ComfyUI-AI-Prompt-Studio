# PH5 Operation Policy Migration

PH5 gives turn-level behavior one executable owner. The versioned
`prompting/operation_policies.py` seam supplies six policies: CREATE, REFINE,
FORMAT_REPAIR, PROTOCOL_RETRY, OBSERVE_TEXT, and OBSERVE_IMAGE.

## Boundaries

- Operation Policy says what the model does this turn.
- Model Core owns ANIMA, Z-Image, Qwen Image Edit, and MiniMax H3 rules.
- Node Core owns semantic schemas, continuity, ChangeSet paths, and PNF ownership.
- Structured task data carries the request, current state, sources, rejected output,
  and concrete issues.
- Output schemas and tagged envelopes remain transport contracts; their PH6
  consolidation is intentionally not claimed here.

REFINE treats the newest request as a delta and preserves unrelated decisions.
FORMAT_REPAIR and PROTOCOL_RETRY may correct only reported defects and preserve
usable facts. Reference observation never invents hidden or unstated attributes.

## Deletions and compatibility

The public nodes already infer CREATE versus REFINE from Session state. PH5 removes
the obsolete `COMPOSER_OPERATIONS` and `H3_OPERATIONS` fields, the disconnected
PromptSource registry, the copied-schema `build_plan_prompt()` helper, and the unused
offline `convert_storyboard()` path. No workflow migration shim is retained because
the removed controls were never part of the current public Studio nodes.

`SemanticChange.operation` (`set`, `delete`, `insert`) remains: it is an internal
transaction primitive, not a user-facing creative operation.

## Acceptance evidence

Contract tests enumerate every operation policy, verify version/layer ownership,
reject private operation sources in production nodes/services, and assert the dead
surfaces are absent. Production tests cover strict and lenient Studio creation,
refinement, repair, storyboard retry, and reference observation assemblies.

# Architecture implementation status

## Completed

- P0–P4.1 persistent prompt/session contracts are implemented and covered by the existing full suite.
- P6 Model Core is the sole runtime owner for target hard rules.
- PH5 Operation Policy Migration is complete: all creative production nodes use
  `prompting/operation_policies.py`; obsolete operation enums and disconnected
  prompt constructors/registries are removed.
- PH6 Schema Contract Cleanup is complete: callers select one `OutputContract`;
  machine schema, prompt summary, provenance, JSON mode, and provider fallback no
  longer drift as separate request flags or copied examples.
- PH7 Markdown Supplemental System is complete under the binding phase numbering:
  schema, registry, import/edit/delete, scope, enable/disable, runtime selection,
  budget, hash/integrity, path safety, UI management, and assembly precedence are
  executable and covered.
- PH8 Node UI Integration is complete: all five supplement-capable nodes expose one
  collapsed Advanced picker backed by the registry, with scope/status diagnostics and
  stable-ID workflow serialization; the raw ID widget is hidden.
- Runtime YAML Prompt Skill loading, CRUD, node injection, settings UI, tests, and `/skills` routes are removed.
- Markdown supplements are implemented end to end: safe local storage, explicit/target/node selection, enable/disable, hash fingerprints, Prompt Assembly provenance, settings UI, and node inputs for LLM, Reference Analyzer, Storyboard Builder, Image Studio, and H3 Studio.

## Deliberately open

- PH9 final prompt-contract regression remains separate.
  No placeholder operation, output-contract, or Skill compatibility path is retained.
- Markdown supplements do not become a second policy language; adding a new hard rule requires a Model Core/code/test change.

# Architecture implementation status

## Completed

- P0–P4.1 persistent prompt/session contracts are implemented and covered by the existing full suite.
- P6 Model Core is the sole runtime owner for target hard rules.
- PH5 Operation Policy Migration is complete: all creative production nodes use
  `prompting/operation_policies.py`; obsolete operation enums and disconnected
  prompt constructors/registries are removed.
- Runtime YAML Prompt Skill loading, CRUD, node injection, settings UI, tests, and `/skills` routes are removed.
- Markdown supplements are implemented end to end: safe local storage, explicit/target/node selection, enable/disable, hash fingerprints, Prompt Assembly provenance, settings UI, and node inputs for LLM, Reference Analyzer, Storyboard Builder, Image Studio, and H3 Studio.

## Deliberately open

- PH6 output-contract migration and later research/UX work remain separate. No
  placeholder operation or Skill compatibility path is retained.
- Markdown supplements do not become a second policy language; adding a new hard rule requires a Model Core/code/test change.

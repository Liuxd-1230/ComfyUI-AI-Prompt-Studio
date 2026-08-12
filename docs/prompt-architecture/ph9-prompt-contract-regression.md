# PH9 Prompt Contract Regression

PH9 is the executable release gate for the prompt architecture. Run it from the
repository root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify_prompt_contracts.ps1
```

The command stops at the first failed contract. It deliberately reuses production
tests instead of maintaining a second mock-only implementation.

| Contract area | Executable evidence |
|---|---|
| Unit rules | renderer, validator, schema, operation-policy, output-contract, supplement, and session tests under `tests/` |
| Integration | node main-flow, aiohttp route loopback, attachment, recovery-journal, and supplement injection tests |
| Mock Gateway | Image/H3 Studio, LLM Generate, Reference Analyzer, and Storyboard node tests capture real `GenerateRequest` assemblies |
| Workflow compatibility | `tests/test_example_workflows.py` checks registered node types, links, public input/output order, and secret absence |
| Node import | `tests/test_smoke_loader.py` loads the extension through ComfyUI-style `spec_from_file_location` and checks every registered node/help contract |
| Python compilation | `compileall` covers every production layer and tests |
| JavaScript syntax | every top-level `web/*.js` file is enumerated on Windows and passed to `node --check` |

Prompt-call ownership remains guarded by
`tests/test_prompt_architecture_inventory.py`: adding a new Gateway or vision call
requires a matching inventory entry and test change. A green PH9 gate proves the
checked contracts; it does not replace an explicit live-provider acceptance run when
provider behavior itself changes.

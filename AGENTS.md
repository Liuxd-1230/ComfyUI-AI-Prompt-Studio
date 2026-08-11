# Repository Guidelines

## Project Structure & Module Organization

This is a Python 3.10+ ComfyUI custom-node extension. The root `__init__.py` registers nodes and web assets. Put node implementations in `nodes/`, data contracts in `schemas/`, integrations in `services/`, prompt output in `renderers/`, and rule checks in `validators/`. Server routes and configuration belong in `server/`; the settings UI lives in `web/`. YAML prompt skills are under `skills/`, workflows under `examples/`, design records under `docs/adr/`, and tests under `tests/`.

## Build, Test, and Development Commands

Create a virtual environment, then install runtime and development dependencies:

```bash
python -m pip install -r requirements.txt
python -m pip install "pytest>=8.0"
python -m pytest tests/
python -m compileall nodes services renderers validators schemas server tests
node --check web/settings.js
node --check web/profile_widgets.js
node --check web/reference_mentions.js
node --check web/prompt_studio.js
```

`pytest` uses ComfyUI-style package loading. `compileall` catches Python compilation issues; `node --check` validates JavaScript syntax. Optional features use `pip install "Pillow>=10.0" "numpy>=1.24"` for vision or `pip install "pypdf>=4.0" "python-docx>=1.1"` for document extraction.

## Binding Refactor Contracts

Before changing any LLM call, prompt assembly, semantic plan, session/revision behavior, Studio UI, model core, Skill/supplement system, renderer, validator, or related schema, read both files under `docs/重构约束/` completely at the current HEAD. `APS_Persistent_Semantic_Architecture_Agent_Prompt.md` and `APS_Whole_Library_Prompt_Architecture_Agent_Prompt.md` are binding architecture and completion contracts, not optional backlogs.

Start at the contract's applicable audit/phase and define its testable acceptance criteria before editing. A feature is incomplete when it uses placeholders, no-op branches, mock-only proof, disconnected UI, swallowed errors, or documentation claims without an executable end-to-end path. Before declaring each work unit complete, audit the diff against both contracts, run all required targeted and full checks, update affected documentation and CHANGELOG, commit the coherent unit, and push it to the configured GitHub remote. Report any unmet criterion as unfinished work instead of weakening or relabeling it.

Contract completion is phase-specific: an unstarted later phase must keep its stated interfaces and migration direction open, but is not reported as implemented. Track partial and missing acceptance cases in `docs/重构约束/implementation-status.md` instead of weakening future requirements or adding placeholder behavior.

## Coding Style & Naming Conventions

Follow existing files: four-space indentation and type hints for Python; two-space indentation, semicolons, and camelCase for JavaScript. Use `snake_case` for modules/functions, `PascalCase` for schema classes, and the `APS_` prefix for ComfyUI node classes. Keep renderers and validators deterministic and side-effect free where possible. Internal Python imports must remain package-relative because ComfyUI loads the extension via `spec_from_file_location`. No formatter or linter is configured, so match nearby code and keep changes focused.

## Testing Guidelines

Tests use pytest and must be named `tests/test_*.py`; test functions use `test_*`. Reuse fixtures from `tests/conftest.py` and import project code through `aps.*`, never as top-level subpackages. Add focused unit tests plus a main-flow or loader regression test when changing node registration, routes, schemas, or workflows. Run the full suite before submitting; no numeric coverage threshold is currently enforced.

## Commit & Pull Request Guidelines

History favors concise, outcome-oriented subjects, often prefixed by a release or batch (for example, `0.2.1c: move workbench entry...` or `Batch D: ...`). Keep each commit coherent and mention user-visible behavior. Pull requests should explain motivation and scope, list verification commands, link relevant issues, and include screenshots for `web/` UI changes. Update `README.md`, `CHANGELOG.md`, examples, or ADRs when behavior or architecture changes.

## Security & Configuration

Never commit API keys, `.env`, `config.local.json`, generated logs, or private files under `docs/sources/`. Secrets must stay in the ComfyUI user configuration and must not enter workflow JSON, node payloads, tests, or logs.

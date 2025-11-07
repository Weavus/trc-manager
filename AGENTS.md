# AGENTS.md
Scope: Root; applies to entire repo.
Cursor/Copilot rules: none found (.cursor/rules, .cursorrules, .github/copilot-instructions.md).
Build/Install
- Python: use `uv`; install `uv sync`; build `uv build`.
- Node: `npm ci`; build `npm run build` (if defined).
Lint/Format
- Python: `uv run ruff check .` (fix: `--fix`), `uv run ruff format .`.
- Node: `npx eslint .` (fix: `--fix`), `npx prettier -w .`.
Test (incl. single-test)
- Python: `uv run pytest -q`; single: `uv run pytest tests/test_file.py::TestClass::test_name -q`.
- Node: `npm test --silent`; single: `npx vitest tests/file.test.ts -t "name"` or `npx jest path -t "name"`.
Code Style
- Imports: stdlib/third-party/local grouped; no unused; prefer absolute.
- Formatting: diff-friendly; ~100 cols; no trailing spaces.
- Types: add hints (Py) and strict TS; avoid any/Optional without reason.
- Naming: snake_case (Py), camelCase (JS), PascalCase for classes/types; CONSTS UPPER_SNAKE.
- Errors: raise specific; don’t swallow; include context; log with logger/console.error only.
- Tests: small and deterministic; name `test_*`; use fixtures/fakes over sleeps.
Git: use focused branches and clear commits; run lint+tests before PR.

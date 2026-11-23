# Testing

- **Fast tier** while working: `.venv/bin/python -m tools.affected_tests --run` runs ruff,
  compileall and the tests a change can affect, contract tests included. `--explain` prints why
  each test was selected. CI runs it on branches and pull requests.
- **Full suite** once before you finish: `.venv/bin/python -m pytest -q -W error -n 8`; warnings
  are failures; `-n 0` debugs serially; `-m "not slow"` is for local iteration only. CI runs every
  test under `TZ=UTC` and `TZ=Asia/Singapore` on each `main` push that changes code.
- **Lint**: `.venv/bin/ruff check .` blocks. `ruff check --select C90 server tools` is advisory
  (complexity findings are not defects); the other selections in CI block.
- **UI**: `npm test` and `npm run build` from `ui/`.
- Tests use in-memory or `tmp_path` DuckDB only and never touch a live store or the network.
- `tests/content_reads.json` records which tests read content under `data/` and `docs/`; refresh
  it with a full run recorded by `--record-reads` and `tools.affected_tests --save-content-reads`.
- Do not add tests that pin documentation prose. Structural doc checks live in
  `tests/test_documentation_integrity.py` (links resolve, every doc is reachable from
  `docs/README.md`) and `tests/test_operating_contract.py` (budgets, BUILDLOG format, plan headers).

Contribution rules for humans: [`../../CONTRIBUTING.md`](../../CONTRIBUTING.md).

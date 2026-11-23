# tests/ — agent notes

The pytest suite (about 6,000 tests). Run the fast tier while working and the full suite once at
the end; details in [`../docs/change/testing.md`](../docs/change/testing.md).

```bash
.venv/bin/python -m tools.affected_tests --run      # fast tier
.venv/bin/python -m pytest -q -W error -n 8         # full suite; warnings are failures
.venv/bin/python -m pytest -q -W error -n 2 farm/research/tests   # outside testpaths; CI runs it
```

- One `test_<module>.py` per module or feature; shared helpers in `*_test_helpers.py` and
  `conftest.py`; recorded inputs in `fixtures/`.
- `contracts/`: provider replay, runtime environment and no-secrets contracts; the deploy gate runs
  them.
- Repository contracts: `test_operating_contract.py` (budgets, BUILDLOG format, plan headers),
  `test_documentation_integrity.py` (links, doc reachability, runbook constants),
  `test_registration_identity.py`, `test_public_hygiene.py`, `test_no_bare_connect.py`.
- `speed_plugin.py` balances slow tests across workers and enforces the duration budget on `main`;
  mark a test over about 5 s with `@pytest.mark.slow`. `content_reads.json` records which tests read
  `data/` and `docs/` content for the fast-tier selection.

Local rules: tests use in-memory or `tmp_path` DuckDB only and never touch a live store or the
network; both `TZ=UTC` and `TZ=Asia/Singapore` must pass; no new documentation-pinning tests.

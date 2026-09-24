# BUILDLOG — trading-engine

Implementation log in the v2 format defined in [`AGENTS.md`](AGENTS.md), newest entries at the
bottom. Entries before 2026-09-18 (the legacy long-form log, phase exits, environment truth, and
decisions) are preserved verbatim in
[`docs/history/buildlog-2026-07-15-to-2026-09-17.md`](docs/history/buildlog-2026-07-15-to-2026-09-17.md).

<!-- buildlog-format-v2 -->
## 2026-09-18 — Operating contract: maintain mode, scope ledger, drift metrics, plans

- **Why:** owner review of 2026-09-18 (`docs/feedback.md`): loop had drifted into building
  governance for a broker that has no authority; asked for docs, metrics and feedback layers
  that stop long LLM sessions doing work not needed yet, plus follow-up plans.
- **What:** `AGENTS.md` + `CLAUDE.md` (contract, admission test, budgets, session shape, this
  entry format); `docs/scope.md` (in scope / not yet / never / parking list);
  `docs/scope-budget.json` (LOC ceilings for `server`, `tools`, research runtime; entry budget;
  doc-test ceiling); `docs/metrics.md` + `tools/metrics_snapshot.py` publishing
  `data/reports/metrics/`; `docs/feedback.md` seeded; `docs/plans/` P1–P4 proposed;
  `tests/test_operating_contract.py` enforcing all of it; banner on `live-readiness-goal.md`.
  No runtime, strategy, evidence, schedule, or database change.
- **Evidence:** `python -m tools.metrics_snapshot --check-budget` → `budget.ok = true`;
  `pytest -q -W error tests/test_operating_contract.py tests/test_docs*.py` green. Full suite on
  macOS: 345 failures, byte-identical set on untouched HEAD (pre-existing; upstream CI on `main`
  was already red after the 2026-09-17 commit with 42 C901 errors). No new failures.
- **Metrics:** server 45,769 (unchanged) · tools +331 (this tool) · product unchanged ·
  last-10-entry mean 741 lines, 913 hashes — the baseline this format replaces.
- **Next:** nothing admitted. Owner promotes P1 (recommended) in `docs/plans/README.md`.

## 2026-09-18 — Public release: history scrubbed, visibility flipped

- **Why:** owner decision (`docs/feedback.md`, second 2026-09-18 entry) to publish the repo as a
  showcase and case-study target for junxiong.dev/trading-engine.
- **What:** history rewritten with
  `git filter-repo --replace-text` / `--replace-message` for an employer email, the host home
  path, an internal tool name and an agent co-author trailer; force-pushed; visibility public.
  201 commits, dates unchanged. Backdating was requested and refused.
- **Evidence:** fresh clone, `git log main -p | grep -ciE '<the four patterns>'` → 0;
  `gh repo view --json visibility` → PUBLIC.
- **Metrics:** unchanged (docs only).
- **Next:** nothing admitted. Existing clones (the host) must be re-cloned before the next session.

## 2026-09-18 — Resume bounded agent decisions and alpha research

- **Why:** explicit owner instruction to implement constrained agent-controlled decisions and resume algorithm alpha research.
- **What:** approved P5 for one isolated simulator-only agent decision path and P6 for one pre-registered fixed-ETF experiment; kept broker connectivity and real capital forbidden. Frozen the credit-confirmed SPY/BIL charter before its runner or result.
- **Evidence:** `pytest -q -W error` → 2,261 tests passed on the fresh rewritten-main baseline.
- **Metrics:** baseline budget green; approved ceilings recorded before implementation.
- **Next:** implement P5 without a broker submission surface.

## 2026-09-18 — Close reviewed paper-agent and alpha plans

- **Why:** active P5/P6 plus the owner's independent-review completion gate.
- **What:** added authenticated, idempotent agent-only simulator decisions with isolated attribution and no broker/live path; froze and ran one credit-confirmed SPY/BIL hypothesis. Review findings drove rerun, receipt, lifecycle, identity, and sealed-evidence fixes.
- **Evidence:** full warnings-as-errors Python suite, 54 UI tests, production UI/wheel builds, Ruff and focused runtime/evidence tests pass; P6 is `REJECT-V1` over 216 paired months.
- **Metrics:** server 46,424 · tools 6,831 · product 28,894; budget ok.
- **Next:** nothing admitted; keep the agent book paper-only and record P6 without tuning.

## 2026-09-19 — Repair stale Python dependency lock

- **Why:** demonstrated defect: `uv lock --check` exited 1 because `uv.lock` omitted the
  declared runtime dependencies `numpy>=2.0` and `PyYAML>=6.0`.
- **What:** regenerated only the dependency lock metadata from the existing requirements. No
  application, strategy, evidence, schedule, database, broker, or capital behavior changed.
- **Evidence:** `uv lock --check && uv sync --extra dev --frozen && uv run python -m pytest
  -q -W error` passed; dependency audit found no known vulnerabilities.
- **Metrics:** product and frozen runtime source unchanged; lock metadata +4 lines.
- **Next:** nothing else admitted; continue unattended evidence collection.

## 2026-09-19 — Reduce frozen agent-policy validation complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/agent_policy.py` reports
  `_validate_policy` at complexity 22 against the repository CI limit of 10.
- **What:** split the monolithic validator into focused mode, strategy, execution, symbol,
  limit, attribution, and mode-contract checks; no policy or authority changed.
- **Evidence:** focused 108 tests and the full warnings-as-errors suite pass; the exact-file
  C90 gate passes and the repository count falls from 42 to 41.
- **Metrics:** server +24 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce hybrid-veto contract complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/agent_veto_contract.py`
  reports `normalize` at complexity 11 against the repository CI limit of 10.
- **What:** extracted bounded evidence-list validation while retaining the same allowlist,
  uniqueness, text limits, errors, candidate binding, and veto-only authority.
- **Evidence:** focused 59 tests and the full warnings-as-errors suite pass; exact-file C90
  passes and the repository count falls from 41 to 40.
- **Metrics:** server, tools, and product LOC unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce provider scope complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/agent_provider_responses.py`
  reports `_strategy_scope` at complexity 11 against the repository CI limit of 10.
- **What:** extracted provider-ticker resolution while retaining the same universe fallback,
  validation, request order, date range, and captured evidence.
- **Evidence:** focused 71 tests and the full warnings-as-errors suite pass; the targeted C90
  finding is gone and the repository count falls from 40 to 39.
- **Metrics:** server +4 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce shadow-attempt projection complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/agent_shadow_read_models.py`
  reports `_attempt` at complexity 11 against the repository CI limit of 10.
- **What:** separated registration and model-metadata validation while preserving public fields,
  statuses, legacy handling, fail-closed checks, and execution authority.
- **Evidence:** focused 66 tests and the full warnings-as-errors suite pass; the targeted C90
  finding is gone and the repository count falls from 39 to 38.
- **Metrics:** server +8 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce source-observation projection complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/agent_provider_responses.py`
  reports `_stored_source_observation` at complexity 11 against the CI limit of 10.
- **What:** extracted normalized source-value parsing while retaining dataset shapes, hashes,
  receipt linkage, timestamp checks, and fail-closed evidence validation.
- **Evidence:** focused 83 tests and the full warnings-as-errors suite pass; the targeted C90
  finding is gone and the repository count falls from 38 to 37.
- **Metrics:** server +4 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce shadow-event projection complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/agent_shadow_read_models.py`
  reports `_event_metadata` at complexity 13 against the repository CI limit of 10.
- **What:** separated event scanning from terminal projection while preserving duplicate checks,
  statuses, response fallback, usage, proposal metadata, and execution authority.
- **Evidence:** focused 84 tests and the full warnings-as-errors suite pass; the file C90 gate
  is clean and the repository count falls from 37 to 36.
- **Metrics:** server +15 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce human-review verification complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/broker_human_paper_review.py`
  reports `verify` at complexity 11 against the repository CI limit of 10.
- **What:** extracted mode-specific decision-evidence validation while preserving packet shape,
  hashes, summaries, TTL, request binding, and all no-authority controls.
- **Evidence:** focused 138 tests and the full warnings-as-errors suite pass; file C90 is clean
  and the repository count falls from 36 to 35.
- **Metrics:** server +5 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce paper-usage verification complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/broker_paper_usage.py` reports
  `verify_loaded_usage` at complexity 11 against the repository CI limit of 10.
- **What:** separated evidence type and identity checks while preserving lease binding, derived
  counters, uniqueness, UTC windows, transcript state, hashes, and no authority.
- **Evidence:** focused 51 tests and the full warnings-as-errors suite pass; file C90 is clean
  and the repository count falls from 35 to 34.
- **Metrics:** server +8 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce broker snapshot capture complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/broker_reconciliation.py`
  reports `_capture_once` at complexity 11 against the repository CI limit of 10.
- **What:** extracted bounded fill pagination while preserving batch validation, fill limits,
  cursor advancement, account scope, uniqueness, ordering, and inert broker status.
- **Evidence:** focused 70 tests and the full warnings-as-errors suite pass; file C90 is clean
  and the repository count falls from 34 to 33.
- **Metrics:** server +4 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce startup authority scan complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/broker_paper_startup_scan.py`
  reports `scan_startup` at complexity 11 against the repository CI limit of 10.
- **What:** extracted retained-epoch verification while preserving completeness, head and
  transcript checks, identity uniqueness, state classification, and no authority.
- **Evidence:** focused 31 tests and the full warnings-as-errors suite pass; file C90 is clean
  and the repository count falls from 33 to 32.
- **Metrics:** server -1 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce startup readiness assessment complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/broker_startup_readiness.py`
  reports `assess` at complexity 11 against the repository CI limit of 10.
- **What:** extracted deterministic blocker-reason derivation while preserving snapshot stability,
  reconciliation age, unresolved-operation checks, halt state, and no authority.
- **Evidence:** focused 58 tests and the full warnings-as-errors suite pass; `assess` clears C90
  and the repository count falls from 32 to 31.
- **Metrics:** server +26 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce proposal normalization complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/agent_contract.py` reports
  `normalize` at complexity 12 against the repository CI limit of 10.
- **What:** extracted proposal time-window validation while preserving field order, timestamp
  normalization, age/skew/expiry bounds, schema, evidence limits, and no authority.
- **Evidence:** focused 98 tests and the full warnings-as-errors suite pass; file C90 is clean
  and the repository count falls from 31 to 30.
- **Metrics:** server +5 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce paper candidate verification complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/broker_paper_lease.py` reports
  `verify_candidate_assessment` at complexity 12 against the repository CI limit of 10.
- **What:** extracted ordered gate and blocker validation while preserving field shape, hashes,
  trust binding, admissibility requirements, validity window, and no authority.
- **Evidence:** focused 51 tests and the full warnings-as-errors suite pass; the targeted C90
  finding is gone and the repository count falls from 30 to 29.
- **Metrics:** server +5 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce startup assessment verification complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/broker_startup_readiness.py`
  reports `verify_assessment` at complexity 23 against the repository CI limit of 10.
- **What:** separated age, operational-control, recovery-state, and blocker validation while
  preserving schema, hashes, trust binding, ordering, and no authority.
- **Evidence:** focused 70 tests and the full warnings-as-errors suite pass; file C90 is clean
  and the repository count falls from 29 to 28.
- **Metrics:** server -9 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce paper lease validation complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/broker_paper_lease.py` reports
  `PaperAuthorityLease.__post_init__` at complexity 13 against the CI limit of 10.
- **What:** separated model-boundary, risk-limit, symbol, and UTC-window checks while preserving
  validation order, exact errors, immutable normalization, and no authority.
- **Evidence:** focused 62 tests and the full warnings-as-errors suite pass; the targeted C90
  finding is gone and the repository count falls from 28 to 27.
- **Metrics:** server +4 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce paper binding validation complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/broker_paper_lease.py` reports
  `PaperAuthorityBindings.__post_init__` at complexity 14 against the CI limit of 10.
- **What:** separated binding limit normalization and startup-state checks while preserving
  identity validation, risk bounds, release gates, and no authority.
- **Evidence:** focused 62 tests and the full warnings-as-errors suite pass; the targeted C90
  finding is gone and the repository count falls from 28 to 27.
- **Metrics:** server +6 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce authenticated-decision verification complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/broker_human_paper_approval.py`
  reports `verify_authenticated_decision` at complexity 12 against the CI limit of 10.
- **What:** separated selected-policy scope and trusted-window validation while preserving exact
  packet/request binding, external authenticator handling, and no authority.
- **Evidence:** focused 104 tests and the full warnings-as-errors suite pass; file C90 is clean
  and the repository count falls from 26 to 25.
- **Metrics:** server +20 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce backup source-read complexity

- **Why:** demonstrated defect: `ruff check --select C90 tools/backup_database.py` reports
  `_read_source_file` at complexity 11 against the repository CI limit of 10.
- **What:** extracted bounded descriptor reads while preserving no-follow opening, size limits,
  regular-file checks, before/after identity checks, and error translation.
- **Evidence:** focused 131 tests and the full warnings-as-errors suite pass; file C90 is clean
  and the repository count falls from 25 to 24.
- **Metrics:** tools +4 LOC; server and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce hybrid fallback validation complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/agent_paper_evidence.py` reports
  `_hybrid_fallback_reason` at complexity 12 against the repository CI limit of 10.
- **What:** extracted transport/output failure metadata validation while preserving exact event
  sequences, fallback payloads, bounded reasons, request binding, and no authority.
- **Evidence:** focused 54 tests and the full warnings-as-errors suite pass; the targeted C90
  finding is gone and the repository count falls from 24 to 23.
- **Metrics:** server +5 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce submission resolution classification complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/broker_ledger.py` reports
  `_resolution_classification` at complexity 13 against the repository CI limit of 10.
- **What:** extracted immutable order/fill matching while preserving account scope, ambiguity,
  quantity checks, broker-order identity, outcome selection, and no broker activation.
- **Evidence:** focused 69 tests and the full warnings-as-errors suite pass; file C90 is clean
  and the repository count falls from 23 to 22.
- **Metrics:** server +11 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce paper consumption planning complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/broker_paper_consumption_plan.py`
  reports `build_plan` at complexity 12 against the repository CI limit of 10.
- **What:** separated source-evidence and mode-specific intent checks while preserving trust,
  freshness, uniqueness, capacity, commitment bytes, and no authority.
- **Evidence:** focused 72 tests and the full warnings-as-errors suite pass; file C90 is clean
  and the repository count falls from 22 to 21.
- **Metrics:** server +16 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce risk-policy validation complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/broker_risk.py` reports
  `RiskPolicy.__post_init__` at complexity 13 against the repository CI limit of 10.
- **What:** separated policy symbol, numeric-limit, and duration validation while preserving
  identifiers, hashes, limit relationships, exact errors, and no authority.
- **Evidence:** focused 79 tests and the full warnings-as-errors suite pass; the targeted C90
  finding is gone and the repository count falls from 21 to 20.
- **Metrics:** server -24 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce broker-order validation complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/broker_contract.py` reports
  `BrokerOrder.__post_init__` at complexity 14 against the repository CI limit of 10.
- **What:** extracted order-state and fill-consistency validation while preserving identifiers,
  symbols, side, quantities, terminal reasons, order type, and session restrictions.
- **Evidence:** focused 121 tests and the full warnings-as-errors suite pass; file C90 is clean
  and the repository count falls from 20 to 19.
- **Metrics:** server +4 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce dividend evidence validation complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/agent_data_contract.py` reports
  `validate_dividend_fact` at complexity 12 against the repository CI limit of 10.
- **What:** separated revision-policy and raw-evidence checks while preserving schema, source,
  availability, timestamps, revision chains, normalized hashes, and no data mutation.
- **Evidence:** focused 83 tests and the full warnings-as-errors suite pass; the targeted C90
  finding is gone and the repository count falls from 19 to 18.
- **Metrics:** server +3 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce pre-trade snapshot validation complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/broker_risk.py` reports
  `PreTradeSnapshot.__post_init__` at complexity 14 against the repository CI limit of 10.
- **What:** separate snapshot time, evidence, and value validation while preserving fail-closed
  ordering, normalization, exact errors, and no execution authority.
- **Evidence:** focused 84 tests and the full warnings-as-errors suite pass; the targeted C90
  finding is gone and the repository count falls from 18 to 17.
- **Metrics:** server +6 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce retained risk-decision verification complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/broker_risk.py` reports
  `verify` at complexity 19 against the repository CI limit of 10.
- **What:** separate retained decision structure, outcome, and input reconstruction checks while
  preserving validation order, errors, hash binding, recomputation, and no authority.
- **Evidence:** focused 123 tests and the full warnings-as-errors suite pass; the file is C90
  clean and the repository count falls from 17 to 16.
- **Metrics:** server +36 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce retained authority reconstruction complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/broker_paper_startup_store.py`
  reports `_epochs` at complexity 13 against the repository CI limit of 10.
- **What:** separate retained-row field, chain, and binding checks while preserving validation
  order, global and per-epoch continuity, duplicate rejection, and no authority.
- **Evidence:** focused 58 tests and the full warnings-as-errors suite pass; the file is C90
  clean and the repository count falls from 16 to 15.
- **Metrics:** server +27 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce daily-price construction complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/agent_data_contract.py` reports
  `daily_price_fact` at complexity 13 against the repository CI limit of 10.
- **What:** separate immutable-observation revision validation while preserving exact errors,
  normalized identity, availability, provenance limitations, and shadow-only authority.
- **Evidence:** focused 62 tests and the full warnings-as-errors suite pass; the targeted C90
  finding is gone and the repository count falls from 15 to 14.
- **Metrics:** server -4 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce daily-price validation complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/agent_data_contract.py` reports
  `validate_daily_price_fact` at complexity 14 against the repository CI limit of 10.
- **What:** separate revision-policy and raw-evidence checks while preserving schema, source,
  availability, timestamps, normalized hashes, exact errors, and shadow-only authority.
- **Evidence:** focused 62 tests and the full warnings-as-errors suite pass; the file is C90
  clean and the repository count falls from 14 to 13.
- **Metrics:** server +12 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce discrepancy evidence validation complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/agent_data_discrepancy_review.py`
  reports `_verified_contents` at complexity 13 against the repository CI limit of 10.
- **What:** separate source-observation and optional-cache verification while preserving exact
  schemas, hashes, time checks, fail-closed errors, and no mutation or authority.
- **Evidence:** focused 63 tests and the full warnings-as-errors suite pass; the file is C90
  clean and the repository count falls from 13 to 12.
- **Metrics:** server +3 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce paper-book row verification complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/agent_paper_attribution.py`
  reports `_verify_book_rows` at complexity 13 against the repository CI limit of 10.
- **What:** separate fill, position, and dividend row checks while preserving SQL ordering,
  ownership, reconciliation arithmetic, tolerances, errors, and no execution authority.
- **Evidence:** focused 67 tests and the full warnings-as-errors suite pass; the file is C90
  clean and the repository count falls from 12 to 11.
- **Metrics:** server +25 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce proposal attribution complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/agent_attribution_read_models.py`
  reports `_proposal_attribution` at complexity 12 against the repository CI limit of 10.
- **What:** separate proposal-validation evidence interpretation while preserving database and
  context binding, reason parsing, order claims, exact errors, and no execution authority.
- **Evidence:** focused 74 tests and the full warnings-as-errors suite pass; the targeted C90
  finding is gone and the repository count falls from 11 to 10.
- **Metrics:** server +23 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce attribution record complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/agent_attribution_read_models.py`
  reports `_record` at complexity 14 against the repository CI limit of 10.
- **What:** separate terminal contribution dispatch while preserving context and status checks,
  model-contact consistency, terminal hashing, exact errors, and no execution authority.
- **Evidence:** focused 74 tests and the full warnings-as-errors suite pass; the targeted C90
  finding is gone and the repository count falls from 10 to 9.
- **Metrics:** server +11 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce attribution read-model complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/agent_attribution_read_models.py`
  reports `attribution` at complexity 14 against the repository CI limit of 10.
- **What:** separate bounded attempt loading and policy-summary construction while preserving
  SQL, limits, registration checks, status precedence, output shape, and no authority.
- **Evidence:** focused 74 tests and the full warnings-as-errors suite pass; the file is C90
  clean and the repository count falls from 9 to 8.
- **Metrics:** server +25 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce attribution migration complexity

- **Why:** demonstrated defect: `ruff check --select C90 tools/migrate_agent_paper_attribution.py`
  reports `migrate` at complexity 12 against the repository CI limit of 10.
- **What:** separate backup and source-location preflight while preserving verification order,
  transaction and rollback boundaries, scoped schema checks, output, and no authority.
- **Evidence:** focused 83 tests and the full warnings-as-errors suite pass; the file is C90
  clean and the repository count falls from 8 to 7.
- **Metrics:** tools +16 LOC; server and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce paper-book initialization complexity

- **Why:** demonstrated defect: `ruff check --select C90 tools/initialize_agent_paper_book.py`
  reports `initialize` at complexity 13 against the repository CI limit of 10.
- **What:** separate input, backup, and plan preflight while preserving validation order, the
  atomic transaction, rollback and scope proofs, inactive output, and no authority.
- **Evidence:** focused 92 tests and the full warnings-as-errors suite pass; the file is C90
  clean and the repository count falls from 7 to 6.
- **Metrics:** tools +22 LOC; server and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce proposal-result validation complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/agent_proposals.py` reports
  `_validate_result` at complexity 18 against the repository CI limit of 10.
- **What:** separate validation identity, context binding, and outcome consistency while
  preserving check order, exact errors, public shape, replay semantics, and no authority.
- **Evidence:** focused 63 tests and the full warnings-as-errors suite pass; the file is C90
  clean and the repository count falls from 6 to 5.
- **Metrics:** server +13 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce retained hybrid-terminal complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/agent_paper_evidence.py` reports
  `_hybrid_terminal` at complexity 15 against the repository CI limit of 10.
- **What:** separate retained event parsing and model-decision verification while preserving
  event order, times, hashes, fallback semantics, exact errors, and no execution authority.
- **Evidence:** focused 106 tests and the full warnings-as-errors suite pass; the file is C90
  clean and the repository count falls from 5 to 4.
- **Metrics:** server +35 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce provider-fact parsing complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/agent_provider_responses.py`
  reports `_facts` at complexity 17 against the repository CI limit of 10.
- **What:** separate series parsing, daily bars, and corporate actions while preserving exact
  validation errors, duplicate rejection, normalized values, hashes, and no data mutation.
- **Evidence:** focused 55 tests and the full warnings-as-errors suite pass; the file is C90
  clean and the repository count falls from 4 to 3.
- **Metrics:** server +19 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce emergency-stop coordination complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/broker_emergency_stop.py`
  reports `cancel_all_and_halt` at complexity 18 against the repository CI limit of 10.
- **What:** separate start-event establishment and cancellation execution while preserving
  halt-first ordering, replay, uncertainty, acknowledgements, exact errors, and no authority.
- **Evidence:** focused 30 tests and the full warnings-as-errors suite pass; the file is C90
  clean and the repository count falls from 3 to 2.
- **Metrics:** server +63 LOC; tools and product unchanged; budget remains green.
- **Next:** continue the remaining CI complexity debt one admitted slice at a time.

## 2026-09-19 — Reduce authority-transcript verification complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/broker_paper_authority_transcript.py`
  reports `verify_transcript` at complexity 26 against the repository CI limit of 10.
- **What:** separate event-chain, activation, consumption, revocation, and state checks while
  preserving their order, cumulative limits, exact errors, hashes, and no execution authority.
- **Evidence:** focused 84 tests and the full warnings-as-errors suite pass; the file is C90
  clean and the repository count falls from 2 to 1.
- **Metrics:** server +11 LOC; tools and product unchanged; budget remains green.
- **Next:** address the final CI complexity finding in one admitted slice.

## 2026-09-19 — Reduce shadow-runner orchestration complexity

- **Why:** demonstrated defect: `ruff check --select C90 server/agent_shadow_runner.py` reports
  `run` at complexity 33 against the repository CI limit of 10.
- **What:** separate policy admission, locked attempt preparation, replay/recovery, and connector
  completion while preserving locking, transactions, failure evidence, and no authority.
- **Evidence:** focused 118 tests and the full warnings-as-errors suite pass; repository C90 is
  clean, reducing the finding count from 1 to 0.
- **Metrics:** server +21 LOC; tools and product unchanged; budget remains green.
- **Next:** perform the goal completion audit against current ratings and evidence.

## 2026-09-19 — Refresh source-bound fault-drill evidence

- **Why:** demonstrated operational gap: `GET /agent/fault-drills` reported `stale` after the
  reviewed source changed, so current recovery behavior was not yet attested.
- **What:** ran the frozen application state-machine drill suite and appended one source-bound,
  non-authorizing result to the existing live evidence ledger.
- **Evidence:** `python -m server.agent_fault_drills run` passed 28/28 cases with zero failures
  and zero indeterminate results; both CLI status and the API now report `current_pass`.
- **Metrics:** server, tools, and product LOC unchanged; budget remains green.
- **Next:** audit the failed Friday miner/postflight cohort without masking upstream gaps.

## 2026-09-19 — Exclude inactive names from intraday collection

- **Why:** demonstrated defect: the live intraday selector returned 931 names including inactive
  `AVB` and `WBS`; those exact names caused the two persistent failed-ticker results.
- **What:** constrain liquidity-ranked intraday names to the current active/liquid universe while
  preserving latest-screen passers, core ETFs, append-only storage, and honest gap reporting.
- **Evidence:** focused 130 tests and the full warnings-as-errors suite pass; the live selector
  still returns 931 names but now includes zero inactive names instead of two.
- **Metrics:** engine +2 LOC; tools and product unchanged; budget remains green.
- **Next:** let the next scheduled miner verify fresh-source behavior; keep Friday failed.

## 2026-09-19 — Recover intraday miner evidence

- **Why:** the Friday farm stage lost a transient DuckDB lock race, leaving the latest intraday
  evidence at `issues`; the writer is now free and the corrected selector is deployed.
- **What:** enqueue and drain one standard intraday job through the existing guarded queue; do
  not backdate evidence or rewrite the immutable failed Friday postflight receipt.
- **Evidence:** job 511 completed with 931/931 tickers covered, zero failed tickers and batches;
  live `GET /meta` now reports the miner cohort `current` at 4/4.
- **Metrics:** server, tools, and product LOC unchanged; budget remains green.
- **Next:** keep the historical failed Friday receipt and verify the next scheduled postflight.

## 2026-09-19 — Reload the API after verified source changes

- **Why:** demonstrated operational defect: the API process entered active state at 03:55 UTC,
  before the latest reviewed source commit at 16:43 UTC, so health was green on stale code.
- **What:** restart only the loopback user API service, then verify health, core read models, and
  the continued absence of paper/broker order routes.
- **Evidence:** the service restarted on a new process; `/health` and `/meta` return 200, fault
  drills remain `current_pass` at 28/28, and all four prohibited routes return 404.
- **Metrics:** server, tools, and product LOC unchanged; budget remains green.
- **Next:** wait for scheduled evidence unless another defect is demonstrated.

## 2026-09-19 — Activate the approved improvement roadmap

- **Why:** the owner approved P1-P4, confirmed continued work, and authorized pushing verified
  commits to the configured upstream.
- **What:** activate P1; approve P2's listed retire set and P3/P4 subject to their explicit owner
  choices; record remote-publication authority without enabling broker or capital access.
- **Evidence:** focused documentation checks and the full warnings-as-errors suite pass; all
  static gates pass and the four plan files/index agree on their new states.
- **Metrics:** server, tools, and product unchanged; budget remains green.
- **Next:** execute P1 in its specified order, one logical change per session.

## 2026-09-20 — Select separate data and execution vendors

- **Why:** the owner delegated the provider choice, with Moomoo and IBKR as likely candidates,
  and approved choosing the system-compatible long-term direction.
- **What:** select IBKR for eventual execution, Sharadar for P3 research data, Norgate as the data
  fallback, and Moomoo as the secondary broker; keep purchase and connectivity disabled.
- **Evidence:** `uv run python -m pytest -q -W error` reached 100%; the settled 18-result
  walk-forward cohort reports `current` with one signature, and UI tests/build are green.
- **Metrics:** server, tools, and product unchanged; budget remains green.
- **Next:** resume P1; P3 waits for a spend ceiling and P4 waits for the new P7 plan.

## 2026-09-20 — Define the autonomous three-mode paper trial

- **Why:** the owner approved S$10,000 simulated starting capital, fully autonomous AI paper
  decisions, several months of observation, and comparison with algorithm and hybrid controls.
- **What:** activate P7 with three paired simulator books, frozen safety/currency contracts,
  logging and observability gates, a 90-day operational pilot, and no broker authority.
- **Evidence:** `uv run python -m pytest -q -W error` reached 100%; 54 UI tests, production build,
  operating-contract checks, static gates, and live scheduler/model-status inspection are green.
- **Metrics:** server, tools, and product unchanged; approved P7 ceilings remain green.
- **Next:** implement P7 trial identity and read-only status before any portfolio mutation.

## 2026-09-20 — Add fail-closed P7 trial readiness status

- **Why:** P7 scope item 1 requires immutable trial identity and honest activation blockers before
  any portfolio, scheduler, or simulator mutation.
- **What:** add the hash-bound three-arm manifest and one bounded read-only status route; semantic
  gates reject forged hashes, dummy books, and incompatible legacy P5 artifacts.
- **Evidence:** full warnings-as-errors suite reached 100%; live status is blocked on 13 named
  gates with no execution authority, and UI/static gates pass.
- **Metrics:** server +590, tools/product unchanged; approved P7 budget remains green.
- **Next:** freeze P7 target-choice/hold semantics and response-bound model identity contract.

## 2026-09-20 — Bind Trae observable identity for paper use

- **Why:** P7 scope item 2 and a live probe showed the model works but its bridge discarded the
  upstream family/request metadata and pinned an older CLI runtime.
- **What:** bind proxy source, runtime, catalog/routing, upstream family and request identities on
  every new response; preserve schema-v2 evidence and keep immutable revision as a live-capital gate.
- **Evidence:** real tool-free inference returned strict no-action with the complete identity; full
  Python, 11 proxy, 54 UI, production-build, and static gates pass.
- **Metrics:** server +38, tools/product unchanged; approved P7 budget remains green.
- **Next:** freeze the AI target-choice and explicit cash-versus-hold contract.

## 2026-09-20 — Define P7 tri-arm attribution contract

- **Why:** P7 requires immutable return ownership before any autonomous simulator writer exists.
- **What:** add a pure verifier for trial/cohort/arm/FX, decision, order, fill, cost, attempt,
  lifecycle, exposure, and aligned-equity evidence; no schema or live-store mutation is included.
- **Evidence:** full warnings-as-errors suite reached 100%; 31 attribution/adjacent tests, 54 UI
  tests, production build, static gates, and cross-book/cost/equity adversarial cases pass.
- **Metrics:** server +579, sim +234, tools/product unchanged; approved P7 budgets remain green.
- **Next:** implement the backup-gated atomic P7 schema and three-book initializer.

## 2026-09-22 — Repin the reviewed Trae proxy source

- **Why:** demonstrated defect: live `GET /agent/model/status` returns 503 with `Trae proxy
  source identity is invalid` after the reviewed proxy deployment changed only tool-message
  translation, leaving scheduled signal-date model decisions fail-closed.
- **What:** repin the exact deployed proxy source and update the P7 proposal/veto and manifest
  identities; the model, prompts, tool-free boundary, risk, strategy, and authority stay unchanged.
- **Evidence:** the full warnings-as-errors suite reaches 100%; live connector status now binds
  `GPT-5.6-Sol:max`, proxy 0.7, Trae CLI 0.205.1, and the reviewed source identity.
- **Metrics:** server, tools, and product LOC unchanged; budget remains green.
- **Next:** implement P7's backup-gated atomic schema and three-book initializer.

## 2026-09-22 — Approve the daily opportunity-agent plan

- **Why:** the owner directed daily market/news and standout-stock assessment with multi-day
  watches and asked for the bounded simulator implementation now.
- **What:** activate P8 with deterministic candidate ranking, structured daily model judgments,
  trigger-time reassessment, isolated next-open paper execution, and no broker authority.
- **Evidence:** the operating-contract tests pass and the raised P8 ceilings precede source work.
- **Metrics:** source LOC unchanged; server, engine, and sim ceilings raised only by the approved caps.
- **Next:** implement the deterministic daily candidate and assessment evidence core.

## 2026-09-22 — Add the daily standout assessment core

- **Why:** P8 scope items 1-4 require deterministic candidates, exact headline evidence, a
  constrained model contract, append-only outcomes, and replay before alerts can act.
- **What:** rank five liquid daily standouts from price, gap, volume, screen, earnings, and regime;
  retain bounded Yahoo responses; record validated ignore/watch/hold/swing results and alerts.
- **Evidence:** focused P8 tests prove deterministic ranking, exact news receipts, one model call,
  replay without new calls, bounded alerts, and fail-closed malformed output.
- **Metrics:** included in final P8/P9 snapshot; approved caps remain green.
- **Next:** add later-session alert evaluation, fresh reassessment, and isolated simulator orders.

## 2026-09-22 — Add P8 alert, simulator, and status boundaries

- **Why:** P8 scope items 4-6 require multi-session alert state, fresh daily reassessment, isolated
  simulator order derivation, scheduling, and bounded observability.
- **What:** add append-only alert events, later-bar crossing and session expiry, inactive-book
  initialization, capped long-only next-open intents, a status route, and a 02:00 UTC timer.
- **Evidence:** focused P8 and service tests pass alert replay, inactive-book no-order, capped active
  order, no same-day fill, attribution, and read-only status cases.
- **Metrics:** included in final P8/P9 snapshot; approved caps remain green.
- **Next:** initialize the book inactive, install the timer, run one live assessment, then validate all.

## 2026-09-22 — Deploy the daily paper observer

- **Why:** P8 scope item 6 and activation safety require scheduling, an inactive isolated book,
  recovery evidence, bounded status, and a real tool-free model observation.
- **What:** install the 02:00 UTC weekday timer, initialize a US$10k inactive book, expose status,
  and retain the first five model decisions plus two multi-session alerts with zero orders.
- **Evidence:** backup verification and focused integration tests pass; live replay reports five
  assessments, available news, zero orders, inactive book, and no broker route.
- **Metrics:** included in final P8/P9 snapshot; approved caps remain green.
- **Next:** observe daily outcomes; activate simulator execution only after final validation review.

## 2026-09-22 — Approve multi-cadence paper-agent tools

- **Why:** the owner directed hourly, multi-hour, and nightly prompt comparisons, a locked tool-call
  execution flow, self-testing, and a paired algorithm-plus-agent path.
- **What:** activate P9 with observation-only intraday variants, one nightly simulator writer,
  deterministic sizing/risk, exact replay, and a frozen gap-volume algorithm comparator.
- **Evidence:** operating-contract validation will precede P9 runtime source changes.
- **Metrics:** source LOC unchanged; approved ceilings raised by the bounded P9 allowances.
- **Next:** finish P8 validation, then implement P9's typed tool and cadence registry.

## 2026-09-22 — Add locked paper tool and cadence variants

- **Why:** P9 requires distinct hourly, four-hour, nightly, and algorithm-veto identities plus one
  durable tool boundary whose request cannot directly size or route an order.
- **What:** register four non-pooled variants, add shadow intraday observations, and require one
  exact `submit_paper_trade` call before deterministic simulator consumption.
- **Evidence:** the P8/P9 self-test passes four variants, one execution policy, the bounded tool
  schema, no broker route, and focused replay/isolation/risk tests.
- **Metrics:** included in final P8/P9 snapshot; approved caps remain green.
- **Next:** install shadow cadence timers and complete the full-suite/recovery gate.

## 2026-09-22 — Complete the multi-cadence paper-agent flow

- **Why:** P9 requires deployable shadow cadences, an exactly-once trade-tool boundary, a paired
  deterministic comparator, and a self-test before simulator authority is enabled.
- **What:** add DST-safe hourly/four-hour model observers, a durable typed-tool ledger, one exact
  assessment consumer, and a frozen gap-volume candidate with a veto-only comparison projection.
- **Evidence:** focused integration tests and the P8/P9 self-test pass, including later-open fill,
  malformed/replay/inactive-book cases, four variants, one writer, and no broker route.
- **Metrics:** server +1,468, tools +58, product +528, tests +533 since 2026-09-20; budget green.
- **Next:** run the full suite, refresh/install units, activate only the isolated simulator book.

## 2026-09-22 — Register the contaminated 2022 agent replay

- **Why:** the owner requested a few 2022 model decisions using contemporaneous charts and any
  valid fundamentals/news while explicitly accounting for possible training-data memory.
- **What:** freeze four decision dates, AAPL/MSFT/XOM/cash, a 20-session horizon, delayed outcome
  reveal, and unavailable status for the absent 2022 fundamental and news archives.
- **Evidence:** the store has 251 sessions and 3,589 current symbols in 2022 but zero 2022
  fundamentals and no timestamped 2022 news; no present data may be substituted.
- **Metrics:** source LOC unchanged; P10 uses the existing farm ceiling.
- **Next:** run and publish the price-only diagnostic without any promotion claim.

## 2026-09-22 — Run the 2022 agent replay

- **Why:** P10 permits four frozen 2022 decisions under named and blinded chart-only prompts, with
  future prices withheld and absent point-in-time fundamentals/news reported rather than invented.
- **What:** retain eight model decisions and delayed 20-session outcomes; both variants selected
  XOM four times and produced identical diagnostic results, explicitly marked contaminated.
- **Evidence:** rerun uses all retained responses with zero model calls; each variant is 3/4 correct,
  +19.78% compounded, -1.83% max drawdown, and +5.85pp mean excess versus SPY.
- **Metrics:** farm +312 lines; approved budget remains green.
- **Next:** do not promote; collect genuine prospective P8/P9 evidence and acquire audited PIT data.

## 2026-09-22 — Publish the agent-trading review

- **Why:** P8-P10 require a final evidence review separating deployed operation, simulated
  authority, historical diagnostics, and unproven performance.
- **What:** publish the architecture/control audit, correct replay drawdown and direction metrics,
  require exact tool identity, and close P10 while P8/P9 collect prospective evidence.
- **Evidence:** full warnings-as-errors suite reaches 100%; Ruff, dedicated self-test, live status,
  installed schedules, real tool transport, and retained-decision replay all pass.
- **Metrics:** final snapshot is within every approved source budget.
- **Next:** observe P8/P9 unchanged; no promotion before their frozen evidence gates.

## 2026-09-23 — Approve unified forward agent evaluation

- **Why:** the owner identified point-in-time data, execution realism, and inconsistent evaluation
  as the main blockers and asked the box to start building usable historical evidence now.
- **What:** activate P11 for one append-only cross-cadence trace ledger, delayed outcome labels,
  completeness checks, and a researched roadmap without changing P8/P9 policy rules.
- **Evidence:** live audit finds daily evidence in DuckDB, intraday evidence in JSONL, and execution
  attribution in separate ledgers with no unified delayed-label dataset.
- **Metrics:** source unchanged; approved P11 ceilings precede implementation.
- **Next:** implement canonical trace capture and maturity-gated labels.

## 2026-09-23 — Add canonical forward agent traces

- **Why:** P11 requires comparable, point-in-time evidence across daily, hourly, and four-hour
  policies instead of separate DuckDB and JSONL histories.
- **What:** add immutable trace/decision/execution-link tables, exact cutoff/latency/model identity,
  replay healing, and maturity-gated 1/5/10/20-session return and excursion labels.
- **Evidence:** focused evaluation and operations tests pass; live migration reports seven legacy
  artifacts skipped because they predate complete trace identity and creates no fabricated trace.
- **Metrics:** server/tools remain within the approved P11 ceilings.
- **Next:** capture the first native P11 windows and evaluate label completeness after maturity.

## 2026-09-23 — Add canonical forward agent traces

- **Why:** P11 requires comparable point-in-time evidence across daily, hourly, and four-hour
  policies instead of separate DuckDB and JSONL histories.
- **What:** add immutable trace/decision/execution links, exact cutoff/latency/model identity, replay
  healing, and maturity-gated 1/5/10/20-session return and excursion labels.
- **Evidence:** focused tests pass; live migration skips seven legacy artifacts lacking complete
  identity rather than fabricating traces, and initializes a clean forward cohort.
- **Metrics:** server and tools remain within the approved P11 ceilings.
- **Next:** capture the first native P11 windows and audit label coverage after maturity.

## 2026-09-23 — Publish the agent backtesting roadmap

- **Why:** P11 requires a researched, actionable roadmap across point-in-time data, execution
  realism, and consistent model evaluation before more strategy or authority expansion.
- **What:** document bitemporal data, vendor audits, execution tiers, delayed labels, paired metrics,
  contamination probes, and the phased acquisition/evaluation programme.
- **Evidence:** full suite, Ruff, dedicated agent self-test, live migration, status endpoints, and a
  verified post-migration recovery bundle all pass; seven legacy traces remain explicitly skipped.
- **Metrics:** server/tools/product remain within the approved P11 budgets.
- **Next:** let native P11 traces accumulate, then audit first 1/5/10/20-session labels.

## 2026-09-23 — Define the agent research product

- **Why:** P12 admits the owner's complete data, execution, evaluation, and historical-ingestion
  programme while retaining explicit paid-data and broker gates.
- **What:** publish the canonical PRD with users, principles, functional/nonfunctional requirements,
  success gates, phased delivery, and external authority boundaries.
- **Evidence:** operating-contract and documentation-index tests pass; P12 budgets precede source work.
- **Metrics:** source unchanged; bounded P12 ceilings are recorded in the owner ledger.
- **Next:** deliver bitemporal source receipts and execution/evaluation product phases.

## 2026-09-23 — Add bitemporal source facts

- **Why:** P12 requires immutable raw receipts and event/publication/availability/ingestion times
  before provider capture or historical imports can become evaluation evidence.
- **What:** add vendor-neutral receipt and fact tables, stable replay identities, revision chains,
  and an atomic raw-response plus normalized intraday-quote batch writer. Invalid timing, missing
  receipts, duplicate quote identities, and partial batches fail closed.
- **Evidence:** `.venv/bin/python -m pytest -q -W error` passes at 100%, including receipt replay,
  immutable revisions, timestamp validation, centralized transactions, and rollback coverage.
- **Metrics:** server remains below 51,950 lines; all source budgets are green.
- **Next:** wire the existing intraday fetcher to preserve exact raw response bytes through P12.

## 2026-09-23 — Retain exact agent intraday responses

- **Why:** P12 requires first-class raw intraday provenance for every quote admitted to an hourly
  or four-hour agent prompt.
- **What:** replace the bounded observer's DataFrame-only quote fetch with an exact Yahoo chart
  adapter. Retain the same response bytes, request/receipt times, normalized 5-minute bars, and
  receipt hash before admitting a derived quote; malformed responses remain auditable but unusable.
- **Evidence:** the full warnings-as-errors suite passes at 100%; a live SPY probe returned one 200
  JSON response and 157 usable bars, and integration tests prove one fetch plus exact trace linkage.
- **Metrics:** server remains below 51,950 lines; all source budgets are green.
- **Next:** add deterministic maximum-hold/invalidation exits and execution-quality attribution.

## 2026-09-23 — Add deterministic agent exits and shortfall

- **Why:** P12 requires bounded maximum-hold/invalidation exits and complete execution-quality
  attribution without changing the frozen simulator or model authority.
- **What:** freeze each accepted buy's horizon and signal-day-low rule; the P8 post-step lifecycle
  creates an idempotent next-open sell on expiry or breach. Append entry/exit latency, arrival gap,
  simulated fill shortfall, cost, and honest date-only fill precision; expose bounded counts.
- **Evidence:** the full warnings-as-errors suite passes at 100%, including horizon, invalidation,
  replay, exact next-open fill, paired shortfall, and frozen forward-contract regressions.
- **Metrics:** all source ceilings remain within the approved P12 budget.
- **Next:** add paired policy scoring, calibration, missing-window, and contamination reports.

## 2026-09-23 — Add canonical agent evaluation report

- **Why:** P12 requires consistent paired scoring, calibration, coverage accounting, deterministic
  controls, execution metrics, and explicit contamination diagnostics.
- **What:** add an atomic nightly report grouped by immutable policy/model/prompt cohorts, with
  per-horizon accuracy, confusion, Brier/calibration, returns, excursions, latency, tokens, control
  deltas, compatible-window pairs, mature/immature labels, and execution/alert metrics.
- **Evidence:** focused report/CLI/service tests and the full warnings-as-errors suite pass; the live
  report truthfully shows zero native traces and four contaminated named/blinded 2022 pairs.
- **Metrics:** server/tools remain within P12 ceilings; all source budgets are green.
- **Next:** add provider-neutral PIT manifests/import validation and SEC acceptance-time capture.

## 2026-09-23 — Add point-in-time ingestion boundaries

- **Why:** P12 requires a safe vendor-neutral historical import boundary and SEC filing capture
  keyed by exact acceptance time, while paid acquisition and credentials remain owner-gated.
- **What:** add audit-first/apply-explicit manifests into isolated `pit_import_*` tables and a
  five-ticker SEC adapter retaining raw mapping/submission responses plus acceptance-time facts.
  Current SEC mappings explicitly have no historical-membership authority.
- **Evidence:** focused importer/SEC/service tests and the full warnings-as-errors suite pass; the
  live anonymous SEC probe returned 403 and therefore no failing timer or live rows were installed.
- **Metrics:** engine/server/tools remain within P12 ceilings; all source budgets are green.
- **Next:** configure a monitored SEC contact, smoke-test activation, then run final recovery audit.

## 2026-09-23 — Complete PIT and SEC ingestion contracts

- **Why:** completion audit found the initial P12 importer omitted declared coverage/revision
  semantics and could trust an incomplete replay; SEC also needs a real monitored contact identity.
- **What:** require and verify coverage, revision policy, availability policy, file containment,
  checksum, and complete replay rows. Add bounded SEC raw-response and acceptance-time capture; keep
  activation gated because this host's anonymous probe returned HTTP 403.
- **Evidence:** focused PIT/SEC tests and the full warnings-as-errors suite pass at 100%; no live
  database, operational prices, strategy state, or broker route was changed.
- **Metrics:** all source ceilings remain within the approved P12 budget.
- **Next:** run the final manifest, recovery, service, and live-state completion audit.

## 2026-09-23 — Extend recovery identity through P12

- **Why:** P12 recovery review found that the backup copied the database but its named release
  groups did not cover the new opportunity, provenance, evaluation, ingestion, and cadence files.
- **What:** add those runtime modules, tools, schedules, schema sources, and the canonical agent
  evaluation artifact to the release identity consumed by backup creation and verification.
- **Evidence:** release-manifest and backup test suites pass, including exact tree/hash verification.
- **Metrics:** tools remain below the approved P12 ceiling; all source budgets are green.
- **Next:** commit, create and verify a pre-migration backup, initialize live additive schemas, then
  create and verify the post-migration recovery bundle.

## 2026-09-23 — Fix live execution-quality reporting

- **Why:** live schema initialization reproduced a DuckDB binder error because the evaluation
  report joined two `cost_bps` columns without qualifying the selected source.
- **What:** qualify every execution-quality projection and add a row-bearing report regression test;
  regenerate the live empty-cohort report after additive P11/P12 schema initialization.
- **Evidence:** focused report tests pass and live report generation completes with zero fabricated
  traces, labels, fills, PIT imports, or SEC facts.
- **Metrics:** all source ceilings remain within the approved P12 budget.
- **Next:** finish the requirement matrix and post-schema backup/restore rehearsal.

## 2026-09-23 — Exclude agent-only books from historical replay

- **Why:** live `/meta` incorrectly expected a walk-forward artifact for the active P8 book even
  though agent decisions are retained external inputs and its registered strategy is intentionally no-op.
- **What:** classify every `agent_only_policy` configuration as forward-evaluation-only in both
  historical replay and walk-forward registries; expand recovery identity across P8-P12 sources,
  services, schedules, schema, tools, and canonical evaluation evidence.
- **Evidence:** replay, walk-forward, meta, release-manifest, and backup suites pass; shared algorithm
  behavior is unchanged and no synthetic agent result was created.
- **Metrics:** farm/tools remain within P12 ceilings; all source budgets are green.
- **Next:** refresh the affected walk-forward cohort, then perform post-schema recovery rehearsal.

## 2026-09-23 — Bring P12 within phase budgets

- **Why:** completion audit found cumulative P12 server/tool additions exceeded their stricter
  plan allocations even though repository-wide ceilings remained green.
- **What:** move generic bitemporal and intraday adapters into `engine`, consolidate the PIT CLI
  with its importer and SEC CLI with its collector, and fold report publication into its module.
  Recovery identity and the installed daily service now name the relocated files exactly.
- **Evidence:** focused provenance, ingestion, report, service, release-manifest, and backup suites
  pass; P12 net additions are server +743, engine +276, tools +324, farm +4, and sim +0.
- **Metrics:** every P12 phase allocation and repository source ceiling is green.
- **Next:** reinstall the changed service, create/verify post-schema backup, and close the audit.

## 2026-09-23 — Complete bitemporal as-of semantics

- **Why:** P12 completion audit found same-value later observations collapsed and no canonical
  cutoff query or typed security-history event boundary existed.
- **What:** preserve distinct receipt/availability observations, expose latest-revision facts only
  when both available and ingested by a requested cutoff, and validate listing, delisting, symbol,
  share-class, and merger event types through the same immutable fact contract.
- **Evidence:** focused bitemporal, intraday, SEC, and PIT suites pass, including exact replay, later
  same-value revisions, as-of selection, security-event typing, and atomic rollback.
- **Metrics:** engine remains within its P12 allocation and repository ceiling.
- **Next:** finish contamination/window diagnostics and the final recovery/completion audit.

## 2026-09-23 — Complete agent execution attribution

- **Why:** P12 completion audit found fill/cost attribution did not retain the post-fill position,
  cash, and nearest available equity state required for a complete lifecycle record.
- **What:** extend append-only execution-quality rows with post-fill quantity, cash, equity, and
  equity date; qualify joined cost fields and retain null equity honestly before end-of-day marking.
- **Evidence:** focused lifecycle/report tests and the full warnings-as-errors suite pass, including
  entry and deterministic-exit fills and a row-bearing execution report regression.
- **Metrics:** server remains within its P12 allocation and repository ceiling.
- **Next:** complete locally runnable contamination probes and scheduler-window accounting.

## 2026-09-23 — Complete evaluation coverage diagnostics

- **Why:** P12 completion audit found schedule windows uncounted, alert trigger rate mislabeled as
  precision, and three locally runnable contamination probes still marked not run.
- **What:** freeze a DST-aware evaluation start/schedule, report missing due windows, compute alert
  precision only from post-trigger outcomes, and retain separate date-recall, prompt-order, and
  synthetic-trend diagnostic artifacts without altering the original 2022 replay.
- **Evidence:** v1 eight-decision and v2 twelve-decision identities verify; focused evaluation, replay,
  service, and operating-contract suites pass. Synthetic accuracy is 25% with -11.02% compounded.
- **Metrics:** P12 net additions remain within every layer allocation and source ceiling.
- **Next:** run the final full suite, refresh/install services, verify recovery, and publish audit.

## 2026-09-23 — Close evaluation completeness gaps

- **Why:** P12 completion audit found no due-window ledger, trigger rate mislabeled as precision, and
  only the named/blinded contamination probe completed.
- **What:** freeze a DST-aware forward evaluation schedule, report missing due windows and true
  next-session alert precision, move pure analysis into `farm`, and retain separate date-recall,
  prompt-order, and synthetic-trend diagnostics without changing the original 2022 replay.
- **Evidence:** original eight and new twelve decision identities verify; focused replay/report tests
  pass. Date recall selected cash, prompt order retained XOM, synthetic accuracy fell to 25%.
- **Metrics:** every P12 layer allocation and repository source ceiling remains green.
- **Next:** regenerate one coherent final-source walk-forward cohort, full suite, and recovery bundle.

## 2026-09-23 — Add net forward outcome labels

- **Why:** P12 audit found maturity labels exposed gross returns while the product contract requires
  a frozen cost assumption for every shadow and executable decision horizon.
- **What:** retain gross returns and append explicit 20 bp round-trip cost, net return, and net
  excess fields; scoring now reads net outcomes while realized fill quality remains separately linked.
- **Evidence:** maturity/replay and report tests pass; net return is proven below gross return and
  existing zero-label live schema migrates additively without fabricated outcomes.
- **Metrics:** all P12 layer allocations and source ceilings remain green.
- **Next:** complete final full suite, cohort refresh, recovery rehearsal, and audit matrix.

## 2026-09-23 — Freeze the final P12 research source

- **Why:** P12's final evidence cohort must use one immutable runtime-source identity and the
  approved farm allocation had only two lines of remaining capacity.
- **What:** mechanically compact the pure agent-evaluation analysis module without changing its
  paired metrics, schedule coverage, or contamination semantics.
- **Evidence:** `.venv/bin/python -m pytest -q tests/test_agent_evaluation_reporting.py -W error`
  passes all seven tests and Ruff reports no findings.
- **Metrics:** farm 11,637 lines; every repository and P12 source budget remains green.
- **Next:** rebuild one uninterrupted walk-forward cohort, then close validation and recovery.

## 2026-09-23 — Complete the agent research product

- **Why:** P12 closes only after one coherent evidence cohort, live deployment audit, full tests,
  and a post-schema recovery rehearsal.
- **What:** publish the final 18-book walk-forward cohort and agent report, migrate the live schema,
  verify all cadence services, document exact product state, and preserve external authority gates.
- **Evidence:** full warnings-as-errors suite and Ruff pass; cohort is current 18/18; self-test and
  installer audit pass; the 57-table final recovery bundle verifies independently.
- **Metrics:** source unchanged at server 51,042, engine 11,871, farm 11,637, tools 7,333, sim 6,891;
  all repository and P12 allocations remain green.
- **Next:** collect prospective labels; paid data, SEC activation, and any broker work require owners.

## 2026-09-24 — Documentation cleanup, history split, and a timezone defect

- **Why:** owner request of 2026-09-24 (`docs/feedback.md`), plus a reproduction:
  `TZ=Asia/Singapore .venv/bin/python -m pytest -q tests/test_adjudicate_agent_data_discrepancy.py`
  failed with "stored provider response receipt is invalid" and passed only with `TZ=UTC`.
- **What:** receipt times are stored as naive UTC in the provider-response and independent-price
  ledgers (DuckDB shifted aware datetimes to local time). Sixteen dated snapshots and the
  pre-2026-09-18 BUILDLOG moved to `docs/history/` with an index; `docs/plans/README.md` is the
  single plan status table (P11 done); scope lists the P8/P9 timers and the P11 ledger; prose hash
  chains removed; README intro and a how-it-works agent-services section added; host wording
  scrubbed. Doc tests follow the moves; removed assertions pinned only the deleted cohort/source
  hashes (six, in two walk-forward tests).
- **Evidence:** `pytest -q -W error tests/test_operating_contract.py tests/test_docs*.py` passes;
  the reproduction passes under Asia/Singapore, America/New_York, and UTC; zero broken relative
  Markdown links.
- **Metrics:** server +2 lines (51,044); engine, sim, farm, tools unchanged; budget ok.
- **Next:** 134 other tests still fail only under a non-UTC `TZ` (agent/broker ledgers); 124 pass
  once the DuckDB session `TimeZone` is UTC, so the fix belongs at connection setup outside the
  contract-hashed `engine/lib/db.py`. Needs its own admitted pass.

## 2026-09-24 — Admit market-data source hardening

- **Why:** the owner requested Tradingview-API plus stronger realtime and historical datasets.
- **What:** open P13 for an exact-response official-API adapter and encode TradingView's current
  non-display prohibition as a hard admission gate rather than feeding it to automated decisions.
- **Evidence:** upstream source/license review and a live anonymous protocol probe establish
  technical reachability; TradingView terms explicitly bar the requested automated use.
- **Metrics:** source unchanged; P13 uses existing repository headroom with no ceiling increase.
- **Next:** implement the admitted provider boundary, fixtures, live smoke, and tonight's audit.

## 2026-09-24 — Add an admitted market-data boundary

- **Why:** P13 requires better realtime/historical inputs without allowing API availability to
  bypass market-data rights or execution boundaries.
- **What:** add a source registry, exact-response Alpaca IEX snapshot/history adapter, optional
  hourly/four-hour cross-check evidence, trace linkage, and a private environment-file hook.
  TradingView is blocked under its current non-display terms; sequence the nightly report after its
  runner to remove their reproduced DuckDB race; v3 shadow policies require fresh completed bars.
- **Evidence:** focused source/intraday/service/release tests pass; status reports Alpaca unavailable
  before network access and TradingView blocked; the 2026-09-23 nightly rerun completed six decisions.
- **Metrics:** server +487, tools +102, farm net unchanged; P13 and repository caps are green.
- **Next:** owner accepts Alpaca terms/adds credentials for a live smoke, or licenses PIT history.

<!-- append-only-tail: insert new verified entries immediately above this line -->

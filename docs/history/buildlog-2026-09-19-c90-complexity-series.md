# BUILDLOG — 2026-09-19 C90 complexity series

The 42 consecutive v2 entries recorded on 2026-09-19 while clearing the CI complexity (C90)
backlog, moved verbatim from [`../../BUILDLOG.md`](../../BUILDLOG.md) on 2026-09-25 to keep the
live log readable. `BUILDLOG.md` keeps one summary entry in their place. Each entry below is one
single-function refactor with no policy, authority, or data change.

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

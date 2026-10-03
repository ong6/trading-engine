---
plan: P19
title: Offline market-data auditor
status: active
opened: 2026-10-03
owner_decision: Owner directed review and work on the auditor handoff on 2026-10-03; offline implementation scope recorded below
---

# Offline market-data auditor (P19)

## Goal and admission

An offline, deterministic sidecar measures whether a study's declared signal population is
represented by its audited data. An independent reference supplies the denominator. A fictional
known-answer example uses the existing evaluator to show the same fixed rule making money on
selectively incomplete data and losing money on complete data. This is a diagnostic of data
fitness, never a certification of profitability.

The owner's 2026-10-03 instruction to review the handoff and start work admits this bounded
extension. The orchestrator chooses technical details. P3 and completed P18 are dependencies,
not alternative admissions. No additional owner decision is needed for the offline slice.

## M0 review: current evidence

Baseline: upstream and local HEAD `284cb06d60409ce5d7f715e23afa69e820a5da43`, refreshed by
`git pull --rebase origin main` from a clean checkout. No running producer was accessed.
`GET /meta` on loopback was unavailable; no service was started. A metrics dry run reports
budget OK and unchanged code sizes against the current committed snapshot.

| Requirement | Existing behavior | Decision |
|---|---|---|
| Independent per-session coverage | `Universe.eligible` enumerates source tickers (`universe.py:67`); annual `free_source_audit` joins ticker/year, not decision sessions (`tools/free_source_audit.py:46`) | Add independent reference enumeration and per-session/bin counts |
| Missing entire security | An offline two-name reproduction returns audited `['SEEN']`, reference `['OMITTED', 'SEEN']`, self coverage 1/1 vs reference 1/2; omitted name is listed and survivor warning is null | Demonstrated measurement gap; existing eligibility remains valid for simulation and is unchanged |
| Sparse liquidity | `Universe.mdv60` consumes last 60 source-session coordinates then skips missing cells; `Panel.mdv60` takes last 60 valid present observations (`panel.py:154`) | Freeze previous N explicit calendar sessions, minimum valid history, reference only; do not change either existing helper |
| Identity | One listing interval per ticker; reused interval rejected (`universe.py:35`) | Audit ambiguity explicitly; no automatic remapping |
| Availability | Bounded views enforce declared field clocks; `DerivedInput` rejects duplicate ticker/session revisions (`data.py:24`) | Reuse field permissions; distinguish declared clocks from observed proof; unsupported revision evidence is unknown |
| Input identity | Price-source hash binds normalized bars but not all clock declarations; run identity accepts caller data hash | Separate audit identity binds contract, normalized evidence, declarations, reference and optional outcomes; leave old identities unchanged |
| Outcomes | Native event ledger retains rejected/unfilled/open positions, exit flags, complete-path/window exclusions (`simulate.py:180`) | Read native outcome records; do not add a second evaluator or infer omitted attempts from successful trades |
| Terminal loss | Existing delisting lookup retains zero close (`panel.py:178`) | Preserve valid terminal zeros; positive signal/entry predicates stay separate |
| Price checks | Existing report checks independent fill prices (`report.py:45`) | Reuse existing evidence where supplied; basis/action proof absent from raw bars is unknown |
| Reports/holdouts | Deterministic reports and sealed holdouts already exist | Write separately identified JSON/Markdown; never reopen holdout or edit study reports |

This review identifies absent reusable measurements, not a defect in the current evaluator.
The offline reproduction and existing tests use fictional inputs only.

## Scope and file claims

Root integration writer owns the plan, ledger/index, documentation, metrics and final integration.
Workers own separate Git worktrees and the following disjoint paths:

| Owner | Paths | Responsibility |
|---|---|---|
| Core worker | `farm/study/audit.py`, `tests/test_study_audit.py` | Frozen contract/evidence, validation, independent population, coverage and status/identity semantics |
| Example/report worker | `farm/study/audit_report.py`, `farm/study/examples/data_audit.py`, `tests/test_study_audit_report.py`, `tests/test_study_audit_demo.py` | Atomic JSON/Markdown and fictional native-evaluator comparison with independent arithmetic |
| Integration writer | This plan, `docs/plans/README.md`, `docs/README.md`, `docs/scope.md`, `docs/feedback.md`, `docs/product.md`, `docs/scope-budget.json`, `BUILDLOG.md`, focused README entry and generated metrics | Admissions, evidence, review and publication |

Existing simulation, data, panel, protocol, core version, report code and registered files are
read-only dependencies. No exports in `farm/study/__init__.py` are required; use direct imports.

### Frozen semantics for the first slice

- Contract declares schema/version, diagnostic purpose, explicit NYSE decision sessions/clock,
  hard maximum date, reference eligibility rules, N-session trailing window/minimum history,
  price/liquidity thresholds and bins, required fields/lookback, availability evidence standard,
  strict coverage threshold, required checks and capped evidence samples. Reject unknown fields,
  malformed bounds and non-finite serialized values as execution errors, with no audit decision.
- Expected membership comes from supplied reference listing intervals, independently of audited
  bars. Listing/price/liquidity uncertainty remains unresolved, never assumed ineligible. Historical
  membership diagnosis and contemporary availability proof are distinct claims.
- Warmup uses previous N declared calendar sessions excluding the decision session. Gaps count
  against minimum history; absent audited warmup never removes reference-eligible names. No fill
  or interpolation. Unknown tiers remain visible. Explicit calendar validation uses existing NYSE
  rules; do not infer the decision calendar from observed bars.
- Signal inputs and later fill/outcome observations have separate clocks. Mutually exclusive
  primary input reason precedence: missing, invalid, late, unknown, complete; supplemental
  findings preserve additional faults. Availability based only on source rules is labelled
  `declared_rule`; if observed timestamps are required but absent, the check is unknown.
- Check statuses: pass, fail, unknown, not_applicable (with reason). Overall supported requires
  every required check supported; an established blocking violation makes unusable; unknown
  required evidence makes limited. Empty populations have null coverage and explicit reasons.
  Unsupported action/revision/field tracing cannot become a pass through a declaration flag.
- Rows and findings sort canonically; sample caps never cap examined counts. Audit identity binds
  exact contract, snapshots and their clock/basis metadata, reference and optional outcomes,
  audit version and optional existing study identity. Reject mismatched hashes.
- Optional native ledger evidence reports all recorded attempts, exclusions, fallback flags and
  open positions. Counts do not establish a frozen outcome-completeness policy: a required
  outcome quality check remains unknown in this coverage slice. Outcomes do not rewrite signal coverage.
- JSON is canonical; Markdown displays those same counts, identities, decisions and limitations.
  Semantic outputs exclude runtime/environment noise. Write atomically to a caller-owned output
  directory outside tracked `data/`; no database or network access.

## Frozen fictional demonstration

Four fictional securities, 60 reference warmup sessions and one decision session, 2024-03-28.
Every security opens at $100; two close at $102 and two at $94. Reference membership contains
all four; two intervals end on the evaluation date, inclusive. The planted omission removes the two losing
names from audited data. This is labelled hindsight selection demonstrating a fault.

One fixed pre-open strategy emits the same four $10,000 open-auction orders, same-session-close
exit, four $10,000 capital slots, cash benchmark, `ibkr_tiered_auction_v1` primary and
`ibkr_fixed_v1` sensitivity. Signal input is the previous-session close, not the later fill.
The strategy, orders, costs, reference, benchmark and capital do not change between snapshots.

Native evaluation independently reproduced during M0:

| Snapshot | Coverage | Completed / missing entry | Gross P&L | Primary costs | Net / fixed $40,000 |
|---|---|---|---|---|---|
| Selectively incomplete | 2/4 | 2 / 2 | $400 | $10.37032 | +0.9740742% |
| Complete | 4/4 | 4 / 0 | -$800 | $20.41616 | -2.0510404% |

Freeze independent fee arithmetic in the demo tests; never call the evaluator's cost calculation
to construct expected answers. This short diagnostic claims neither six folds nor a sealed
holdout. No private research rules, names, results or hashes enter these artifacts.

## Not in scope

Real-data adapters, publication-time reconstruction, a stable-security identity service, arbitrary
strategy access tracing, collectors, paid data, UI/HTML, dashboards, services, live gates, broker
work, operational migrations, new dependencies, profitability scoring and existing evaluator fixes.
Checks requiring absent evidence remain unknown. A later adapter or visual product needs its own
scope decision. Never reopen a holdout or change frozen study bytes to fit this diagnostic.

## How to run this plan

M0 review is complete. Freeze the typed API and known answers before parallel implementation.
Use one writer per worktree and no database writers. Root integrates disjoint commits and resolves
technical disagreements. Then independently review denominator, clocks, arithmetic, error paths
and compatibility before completion. Continue within this scope without routine checkpoints.

## Done when

```sh
.venv/bin/python -m pytest -q -W error tests/test_study_audit*.py
.venv/bin/python -m farm.study.examples.data_audit --output-dir /tmp/market-data-audit-demo
.venv/bin/python -m pytest -q -W error -n auto
.venv/bin/ruff check .
.venv/bin/python -m tools.metrics_snapshot --check-budget
```

Use serial full pytest if the existing environment lacks xdist; record that limitation. All
focused tests pass: complete/omitted/warmup/unknown/ambiguous/late/invalid/empty/hash corruption,
future-only mutations, evidence truncation, JSON/Markdown parity, exact native demo arithmetic
and unchanged old result/identity bytes. Record real commands/counts, check upstream CI and
verify branch push. Runtime independence is explicit; no local test establishes remote health.

## Budget, risks and rollback

At most 6 logical commits, each below 1,500 inserted non-data lines; up to 1,800
new farm lines, 1,200 new test lines and 600 documentation lines. No dependencies or source
mutations. Small normal-suite fixture: four names × 61 sessions plus focused fault variants.
The bounded profile below establishes this diagnostic's scale only. The future real-data adapter
checkpoint retains the proposed 3,000 × 3,800 target of ≤60 seconds additional audit time and
≤256 MiB additional peak memory above already-built inputs. That target is unverified and is not
a completion claim of this raw-snapshot slice: indexes scale with input rows. Do not construct a
second dense panel or present bounded-fixture results as production-size acceptance.

Main risk is false confidence in imperfect reference/clock metadata. Explicit evidence basis,
unresolved counts and limited status address it. Remove the optional sidecar/example to roll back;
existing study artifacts remain independently readable.

## Progress

- M0: complete; two independent read-only reviewers confirmed seams and fictional arithmetic.
- M1–M3: complete; typed raw snapshots, independent coverage, separate JSON/Markdown and native demo integrated.
- M4: excluded from this first slice.
- M5: independent review cleared; publication and final Linux CI pending.

### Verified implementation evidence (2026-10-03)

- `.venv/bin/python -m pytest -q -W error -o addopts='' tests/test_study_*.py tests/test_operating_contract.py`
  → 123 passed in 12.22 seconds, including all 45 new audit/report/demo cases.
- `.venv/bin/python -m farm.study.examples.data_audit --output-dir /tmp/market-data-audit-demo`
  → incomplete unusable/+0.9740742%, complete supported/-2.0510404%, late input unusable.
  `demo.md`/`demo.json` link separate case audit and unchanged native-report artifacts.
- Whole-repository Ruff and S101 checks pass. Git diff over existing evaluator, engine,
  simulator, server and tools files is empty against the baseline.
- A complete local full-suite run before auditor code was added had 179 failures across 4,358
  cached test nodes. That run already included the new plan; its missing documentation-index
  entry was corrected after CI identified it. Linux-specific descriptor/service checks and
  Python 3.14 differences prevent a local green claim; final Linux CI is required.
- Bounded synthetic profile: 300 securities × 71 input sessions (21,300 raw rows), ten decision
  sessions, 3,000 examined members, supported and zero findings. On 12 logical ARM64 CPUs/macOS,
  Python 3.14.8: snapshot construction/hashing 0.306 seconds; audit 1.183 seconds; no increase in
  process peak RSS after snapshot construction. This does not establish the large-shape target.
- Fresh review reproduced and cleared premature daily-field admission, contradictory renderer
  ratios/decisions, malformed native traces and missing totals under evidence truncation.
  Terminal-zero losses remain valid; unavailable future fields do not change earlier classifications.
- The first full Linux CI run had exactly one failing documentation-index test in each timezone;
  all auditor tests passed. The missing P19 link in `docs/README.md` was added. The orchestrator
  expanded the logical-commit budget by one for this required index correction and final closure;
  code, test and documentation line budgets are unchanged.

<!-- sources: farm/study/data.py, farm/study/universe.py, farm/study/panel.py, farm/study/simulate.py, farm/study/report.py, tools/free_source_audit.py, docs/backtest-standard.md -->

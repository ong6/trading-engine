# Separate paper accounts and private strategy requests

The private alpha layer owns strategy generation, registrations, feasibility planning and
versioned trade specifications. The engine owns accounts, capital, order admission, execution,
positions, fills, cash and equity. Alpha submits requests; it never submits an authoritative
balance, holding or fill. Shared market prices are read-only inputs to every account.

`engine.paper_accounts` is the generic library boundary. It makes no network/model/broker call
and runs no strategy. All mutations use one engine DuckDB writer and a database transaction;
strategy evaluation and request preparation may happen concurrently outside that writer.

## Account creation

`create_account(connection, specification, now=aware_datetime)` validates an exact v1 object:

| Field | Meaning |
|---|---|
| `schema_version` | Integer `1` |
| `account_id`, `strategy_ref` | Opaque identifiers; private values live only in the private runtime |
| `spec_sha256`, `registration_sha256` | Exact private specification/registration content identities |
| `instrument_kind` | `stock` or `etf`; `option` and `future` are explicitly unsupported for execution |
| `capital_usd` | Independently funded `10000`, `50000` or `100000` USD |
| `max_position_fraction` | Positive admission limit no larger than the gross limit |
| `max_gross_fraction` | Positive admission limit at most one; no leverage |
| `min_trade_usd` | Positive minimum trade value compatible with the position limit |

The alpha planner evaluates all requested tiers before results are observed. Its `10k`, `50k`,
`100k`, `all` or `auto` selection produces concrete eligible specifications. The engine does
not guess a profitable capital size. Options/futures can be researched in alpha but cannot
create executable accounts until separate instrument-aware simulator work is approved.

Creation binds the exact specification in `paper_account_specs` and independently funds an
inactive `portfolios` row. Repeating an identical creation is idempotent and never resets cash.
Reusing an existing account ID with another specification or tier is refused. Existing league
accounts and their funding are unchanged. Every account uses its own `portfolio_id` in
`sim_positions`, `sim_orders`, `sim_fills` and `sim_equity`; no separate alpha balance database
exists. The `discretionary` strategy adapter produces no automatic orders for these accounts.

## Intent intake and execution

`validate_spec(spec)` and `validate_intent(intent, spec, now)` are pure checks usable by an alpha
exporter without opening the engine database. `submit_intent(connection, intent, now=...)`
performs the state-dependent checks and accepts an exact v1 request:

`schema_version`, `intent_id`, `account_id`, `spec_sha256`, `registration_sha256`,
`instrument_kind`, `ticker`, `side`, `quantity`, `signal_date`, `created_at`, `source_sha256`.

Quantity is a finite positive number of shares fixed by the prospective specification.
A notional-only frozen request cannot be silently converted using a premarket quote or a
future official open. Historical private paper fills are not replayed through this interface.
The engine admits only requests observed after the signal session's exchange close (including
13:00 early closes) and received before the next session's 09:30 New York open. Both clocks
are checked; backdated requests cannot obtain retrospective fills. The signal session must be
the current stored price session and have an exact reference close.

The engine checks matching account/spec/registration/instrument identities, duplicate intent IDs,
existing pending legs, the account's own holdings, cash and reserved buy requests. Position and
gross limits are admission checks at signal prices; actual gap/slippage outcomes remain governed
by the existing fill model and its cash bounds. An unsupported instrument or failed check leaves
no order and does not activate the account.

A successful intake atomically records `paper_account_intakes`, creates one pending `sim_orders`
row and activates that account. If accounting history exists, every active book must already have
signal-session equity before intake; only then is the new account's equity added to that completed
checkpoint. An unfinished night refuses intake. When the whole equity ledger is empty, all initial
accounts can queue requests, but intake writes no equity: the ordinary league completes their first
signal-session marks together. This prevents one new account's mark from causing the league to
mistake an unfinished night for completed accounting.

An identical retry returns its original order ID even after the admission window closes; changed
evidence under the same ID is refused. The ordinary league fills at the next open and alone records
fills, cash and positions. Parallel alpha producers must route mutations through the one engine
writer.

## Verification

`pytest -q tests/test_paper_accounts.py` exercises three separately funded accounts buying the
same symbol, independent cash/fill/equity and exact state reconstruction; 25 accounts cannot sell
or spend another account's assets. It also checks idempotence without re-funding, immutable
specification identity, early closes, late requests, invalid capital and unsupported instruments.
Bootstrap and existing-league regressions run the ordinary league to prove intake cannot skip a
nightly step or block several accounts from their first next-open fills.
These are accounting/operating proofs, not strategy or profitability claims.

## Version 2 account contract

Version 2 is the service contract for account-engine portfolios. Version 1 remains accepted for
the original next-open library users. A v2 specification has this exact required shape:

`schema_version`, `strategy_ref`, `strategy_version`, `spec_sha256`, `artifact_sha256`,
`registration_sha256`, `instrument_kinds`, `capital_usd`, `account_id`, `account_type`,
`max_position_fraction`, `max_gross_fraction`, `min_trade_usd`, `allow_short`, `price_source`,
`benchmark`, and `day_trades_per_week_expected`. `day_trade_rule` is optional at input and is
persisted as `pdt_25k_legacy` when omitted; it may instead be `intraday_margin_2026`.
`whole_shares` is the only other optional field and defaults to false.

`instrument_kinds` is a non-empty subset of `stock`, `etf`, `option`, and `future`. Structural
validation is available for every kind, but only stocks and ETFs execute. Options, futures, and
multi-leg requests return `instrument_not_executable` until bid/ask execution data is admitted.
Accounts are margin accounts with independent USD 10,000, 50,000, or 100,000 funding. The gross
limit defaults in the private specification and cannot exceed 1.5 times equity. Short orders also
require `allow_short: true`. `price_source` is `prices` or `massive_daily`; `benchmark` is `SPY`.

`spec_sha256` is the account identity: it is calculated by the private planner from the canonical
strategy specification after removing its changing `market` evidence block. `artifact_sha256`
identifies the exact planner artifact but is informational. Re-planning with new market evidence
and a new artifact hash therefore returns the existing account when all identity-bearing and
operating fields are unchanged. Neither operation refunds or resets an account.

The engine records execution settings in `portfolio_accounts`, not by extending `portfolios`.
All readers use the defaulted `portfolio_accounts_v` projection and all writers use the schema
accessor. A v2 account starts with `engine=account`, `visibility=private`, `status=inactive`,
`cost_profile=ibkr_pro_tiered_v1`, its declared price source and day-trade rule, and the declared
short permission. Its `portfolios.created` date is the New York session on its creation date, or
the preceding exchange session on a weekend or holiday.

## Version 2 intents and receipts

A v2 intent contains exactly `schema_version`, `intent_id`, `account_id`, `spec_sha256`,
`registration_sha256`, `instrument_id`, `instrument_kind`, `side`, `quantity`, `order_type`,
`limit_price`, `time_in_force`, `session_date`, `contingent_on`, `legs`, `created_at`, and
`source_sha256`. Sides are `buy`, `sell`, `short`, and `cover`. Order types are `next_open`,
`moo`, `moc`, `market`, and `limit`; time in force is currently `day`. `limit_price` is positive
only for a limit order. `contingent_on` names an earlier intent in the same account. A leg has
only `instrument_id`, `side`, and a non-zero integer `ratio`.

The authoritative `received_at` is stamped by the engine before it waits for the DuckDB writer.
MOO requests are accepted through 09:28:00 New York time. MOC requests are accepted through ten
minutes before that session's scheduled close: 15:50 on ordinary sessions and 12:50 on a 13:00
early close. Market orders are accepted during the regular session. Intraday market and limit fills are deferred until the
nightly minute bars exist; this service does not claim real-time execution. A successful response
is `{order_id, state, received_at, cutoff, refusal_reason}`. Retrying byte-equivalent intent data
under the same `intent_id` returns that original response, including its first receipt timestamp,
even after the cutoff. Reusing the ID for different evidence is refused.

Admission applies holdings, minimum trade, position, per-account gross, and total account-engine
gross limits. Marks may be carried for at most three exchange sessions; the refusal names every
stale instrument. The engine rechecks execution-time margin, PDT, and aggregate liquidity in the
settlement layer. `pdt_25k_legacy` refuses a fourth day trade in five sessions below USD 25,000;
`intraday_margin_2026` has no count limit but still gets only Reg T initial buying power.

## Money layer and lifecycle

After every normal or late mark, the account risk hook halts once at a 20% peak-to-current
drawdown, a 5% close-to-close loss, or a reconciliation mismatch. The durable `account_events.kind`
is respectively `halt_drawdown`, `halt_daily_loss`, or `halt_reconciliation`; consumers never
need to match prose. A halt cancels queued orders, refuses new ones, and keeps positions open and
marked. Resume records `resumed_by` and keeps the all-time peak for reporting. Only a resumed
drawdown halt re-arms that rule from equity at resume; other halt reasons retain the all-time
drawdown threshold. Retirement queues next-session
MOC sell or cover orders, changes the account status to retired, and preserves all history.

Across account portfolios, opening exposure cannot exceed one times the sum of active independent
funding. Holding the same instrument in three accounts, or aggregate notional above 2% of its
MDV60, records a non-blocking concentration alert in each affected private result. The watch route
maintains at most 500 additional symbols for the data collector.

## CLI, loopback API, and private results

`python -m engine.accounts` provides `create`, `submit`, `cancel`, `halt`, `resume`, `retire`,
`list`, `results`, `verify`, and `settle [--late]`. The settle command imports
`engine.accounts.settle.settle_session` only when invoked so this lane can integrate independently
with the settlement lane. `generate-token` creates
`~/.config/trading-engine/accounts-api.token` with mode 0600. Token contents are never printed or
stored in this repository.

The API remains bound to loopback by the server host boundary. `GET /accounts` shows public
accounts without credentials; a valid `Authorization: Bearer <token>` also shows private ones.
Every route that addresses a private account, and every mutation, requires that token. Read routes
cover account state, positions, orders, fills, cash events, equity, and deterministic results;
write routes cover creation, submission, cancellation, reconciliation, halt, resume, retirement,
and the account watch.

Results include the equity curve, total and benchmark return, excess, drawdown and worst daily
loss, fill count/notional, itemized fees and financing costs, closed-trade statistics, trailing
day trades, halt/alert/PDT/margin-call counts, late fills, and latest reconciliation state. The
canonical payload carries its own stable SHA-256. Private results stay in DuckDB and may be copied
only into the private alpha repository; no command writes them below `data/`.

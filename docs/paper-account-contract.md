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
row, activates that account and records its signal-session equity. An identical retry returns its
original order ID even after the admission window closes; changed evidence under the same ID is
refused. The ordinary league fills at the next open and alone records fills, cash, positions and
equity. Parallel alpha producers must route mutations through the one engine writer.

## Verification

`pytest -q tests/test_paper_accounts.py` exercises three separately funded accounts buying the
same symbol, independent cash/fill/equity and exact state reconstruction; 25 accounts cannot sell
or spend another account's assets. It also checks idempotence without re-funding, immutable
specification identity, early closes, late requests, invalid capital and unsupported instruments.
These are accounting/operating proofs, not strategy or profitability claims.

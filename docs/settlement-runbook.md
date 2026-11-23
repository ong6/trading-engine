# Settlement runbook — dead positions

When a held name stops trading, the engine cannot sell it (there is no tradeable bar) and
marks it at its last close; `data/reports/league.md` lists it under "Stale marks". The
engine does not know, and must not guess, a deal price (honesty rule 1: never invent a
price). **You look up the terms; `sim/settle.py` books exactly what you cite.** If nobody
does, the engine closes the holding out at its last real traded close (next section).
Code reaches the live checkout only through the deploy path in
[`change/deploy.md`](change/deploy.md).

## Automatic close-out of a delisted holding

Every active book type closes out a delisted holding through the same `sim_settlements`
row and replay path: the league day-step (phase a1, before fills), each P15 window (before
that session's P15 fills; the open rule closes and pending intents for the name are
cancelled) and each account fold. Retired books are not touched. A holding is delisted on
session `d` when both hold, using only data dated on or before `d`:

1. The exchange directory dropped it: its latest `universe_snapshot` row is inactive, and
   that omission began on or after its last traded bar. A name dropped while it still
   traded is never closed out automatically (BURU and ISSC were, and traded again).
2. It has printed no trusted bar for 5 sessions. Execution, marks and settlement evidence
   require finite positive OHLC, valid geometry and positive volume; a zero-open quote
   like WBD's 40 shares on 2026-10-05 is not one.

The settlement is `cash` at that last traded close, effective the next session, with a
`source` beginning `delisting close-out:` that records the evidence. If a sourced
settlement for the ticker effective after its last trade already exists (you booked the
deal for other books), its terms are used instead. A name that never traded is left
carried. Five sessions gives a trading week to book sourced terms first; no dropped name has
traded again after more than three silent sessions, and the booked amount does not depend on it.

## 1. Look up the terms

For each name, find the primary document and note four things: kind (cash / stock /
mixed / worthless), the per-share consideration, the effective date (deal close or
delisting-effective date, not the announcement), and the URL.

Where to look, in order of authority:

1. SEC EDGAR filings for the target — the 8-K filed at closing (Item 2.01 / 3.01), or the
   DEFM14A merger proxy for the consideration; a Form 25 marks the delisting.
2. The acquirer's or target's closing press release.
3. Exchange notice (Nasdaq/NYSE delisting notices) for a delisting without a deal.
4. Bankruptcy docket / plan confirmation for a cancellation (`--kind worthless`).

News articles and Yahoo quote pages are not sources. If you cannot find a primary
document, book nothing: the automatic close-out above settles it at its last traded close.

## 2. Dry-run (default; opens the store read-only)

Run from the repo root. The dry run prints a before/after table per book and refuses if
the ticker has a traded bar on or after `--effective`, if `--source` is missing, or if
the acquirer has no trusted stored prices. Nonfinite, negative or invalid zero terms
are refused before any write, as is arithmetic that would overflow cash, shares or basis.
Worthless settlements keep a zero price; stock terms may keep a zero cash leg.

```bash
# Cash deal: every holder receives qty × price on the effective date.
.venv/bin/python -m sim.settle --db store/market.duckdb --ticker EA \
    --kind cash --price "<PRICE>" --effective "<YYYY-MM-DD>" \
    --source "<EDGAR URL of closing 8-K or press release>"

.venv/bin/python -m sim.settle --db store/market.duckdb --ticker TALK \
    --kind cash --price "<PRICE>" --effective "<YYYY-MM-DD>" --source "<URL>"

.venv/bin/python -m sim.settle --db store/market.duckdb --ticker WBS \
    --kind cash --price "<PRICE>" --effective "<YYYY-MM-DD>" --source "<URL>"

.venv/bin/python -m sim.settle --db store/market.duckdb --ticker FBRX \
    --kind cash --price "<PRICE>" --effective "<YYYY-MM-DD>" --source "<URL>"
```

Other shapes, same flags otherwise:

```bash
# Stock-for-stock: R acquirer shares per held share. Acquirer must have real bars.
... --kind stock --into "<ACQ>" --ratio "<R>"
# Mixed: R shares plus cash per share.
... --kind stock --into "<ACQ>" --ratio "<R>" --price "<CASH_PER_SHARE>"
# Cancelled / bankrupt: position to zero, no cash.
... --kind worthless
# Only some books (default is every active holder):
... --portfolio high_52wk,low_vol
# Free-text context that goes into the ledger row:
... --note "Cash election; CVR ignored (not priced)"
```

`--effective` is the date the terms took effect. The engine checks the ticker printed no
traded bar on or after it. For EA the last real trade was 2026-08-04, so `--effective` must
be 2026-08-05 or later; use the date from the filing, not the last-trade date.

## 3. Apply

Only after the dry-run table is what the filing says. Not while the nightly is running
(22:30 UTC weekdays) or a farm job holds the writer lock; `db.connect` retries the lock
for 60 s then fails, which is fine.

```bash
.venv/bin/python -m sim.settle --db store/market.duckdb --ticker EA \
    --kind cash --price "<PRICE>" --effective "<YYYY-MM-DD>" --source "<URL>" --apply
```

One transaction per command: one `sim_settlements` row per book, cash credited,
position set to 0 (or converted), and any matching pending order cancelled as obsolete.
The command writes one `settlement_applied` audit row containing the affected books and
cancelled order ids. A linked discretionary ticket is cancelled with its order so the two
ledgers agree. `prices`, fills, and `sim_equity` are not touched.

Stores with settlements booked before pending-order cancellation was added can be checked
without writing, then repaired in one transaction:

```bash
.venv/bin/python -m sim.settle --db store/market.duckdb --reconcile-pending
.venv/bin/python -m sim.settle --db store/market.duckdb --reconcile-pending --apply
```

`--ticker FBRX` narrows either command. The reconciler only selects pending orders whose
signal date is earlier than the matching settlement's booking date. Old orders have no
creation timestamp, so ambiguous same-day intent is deliberately left for manual review.
This prevents an old settlement from cancelling an unusual but deliberate later order.

## 4. Verify

```bash
.venv/bin/python - <<'EOF'
import duckdb
c = duckdb.connect('store/market.duckdb', read_only=True)
print(c.execute("SELECT portfolio_id, ticker, kind, qty, price, into_ticker, ratio, "
                "effective, source FROM sim_settlements ORDER BY created_at").fetchall())
print(c.execute("SELECT p.portfolio_id, p.ticker, p.qty FROM sim_positions p "
                "JOIN portfolios b ON b.id=p.portfolio_id "
                "WHERE b.active AND p.ticker IN ('EA','TALK','WBS','FBRX','CRNX','APGE') "
                "AND p.qty > 0").fetchall())
print(c.execute("SELECT id, portfolio_id, ticker, status, reject_reason FROM sim_orders "
                "WHERE ticker IN ('EA','TALK','WBS','FBRX','CRNX','APGE') "
                "AND status = 'pending'").fetchall())
EOF
```

The second and third queries should be empty for every active book. After the next nightly step
the name is gone from the "Stale marks" table in `data/reports/league.md`, and each
book's equity moves from the frozen mark to the settlement value.

`.venv/bin/python -m pytest -q tests/test_settle.py` covers the arithmetic, refusals,
atomic pending-order cancellation, legacy reconciliation, and rebuild/rerun survival.

## What `--source` should cite

A URL or filing reference a third party could open and read the same number from:
`https://www.sec.gov/Archives/edgar/data/<CIK>/<accession>/<doc>.htm` for an 8-K /
DEFM14A / Form 25, the acquirer's IR press-release URL, or an exchange notice URL. Add
`--note` for anything the URL does not make obvious (cash election, fractional-share
cash-in-lieu, CVRs you are deliberately valuing at zero). The string is stored verbatim
in the ledger row and is the only evidence the number came from anywhere.

## Behaviour to know about

- **Rebuild and `--rerun`.** `portfolio.rebuild_state` replays settlements as their own
  event kind at `effective`, after that day's dividends and before its fills, at the
  recorded qty and price. `rerun_cleanup` deletes a date's fills/dividends/equity but
  never settlement rows, so a rerun reproduces the settlement exactly. If a fill before
  `effective` is later added or removed, the replay prints a WARN that the recorded qty
  no longer matches the rebuilt position.
- **Equity history.** `sim_equity` rows before `effective` are untouched. Rows from
  `effective` up to the apply date keep the frozen mark they were written with (the dry
  run tells you how many); they are the point-in-time record of what the league believed.
  Nothing restates them.
- **Signed holdings.** Cash terms credit longs and debit shorts; worthless events remove either
  signed position without inventing cash. Stock conversions preserve the sign and open lots in
  the acquirer. The acquirer lot's avg_cost is the dead lot's avg_cost ÷ ratio, merged into any
  existing same-side acquirer lot; no P&L is realised on the swap.
- **Re-settling.** A `(portfolio, ticker, effective)` primary key blocks a duplicate row.
  Settling a name a book no longer holds is refused (nothing to do), so re-running an
  applied command exits 2 rather than double-crediting.
- **Inactive books** are skipped: `holders` only considers `portfolios.active = TRUE`.
- **Pending orders.** Applying a settlement cancels every matching pending order in the
  same transaction because the settled position no longer exists. This is booking-time
  lifecycle work, not settlement replay: `rebuild_state` reconstructs cash and positions
  without retroactively changing an order created after the settlement was booked.


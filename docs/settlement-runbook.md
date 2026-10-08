# Settlement runbook — dead positions

When a held name stops trading, the engine cannot sell it (there is no tradeable bar) and
marks it at its last close; `data/reports/league.md` lists it under "Stale marks". The
engine does not know, and must not guess, what happened (honesty rule 1: never invent a
price). **You look up the terms; `sim/settle.py` books exactly what you cite.**

The table below is the original 2026-09-02 snapshot retained as incident history. All four
were subsequently settled from primary filings.

| Ticker | Last real trade | Held by (qty, as of 2026-09-02) |
|---|---|---|
| EA | 2026-08-04 | high_52wk 7.4335, low_vol 6.1946 |
| TALK | 2026-08-14 | high_52wk 298.8506 |
| WBS | 2026-08-19 | high_52wk 20.202 |
| FBRX | 2026-08-26 | ew_benchmark 10.1828, momo_stopped 50.4191, template_top10_banded 42.7027, template_top10_banded_gated 42.7027, news_gated_momo 44.7129 |

## Applied ledger events — through 2026-09-07

The active paper books were settled from the closing 8-Ks and independently verified:

| Ticker | Terms | Effective | Primary source |
|---|---|---|---|
| EA | $210 cash/share | 2026-08-05 | [closing 8-K](https://www.sec.gov/Archives/edgar/data/712515/000114036126031157/ef20079099_8k.htm) |
| TALK | $5.25 cash/share | 2026-08-17 | [closing 8-K](https://www.sec.gov/Archives/edgar/data/1803901/000095015726000907/form8-k.htm) |
| WBS | 2.0548 SAN ADS + $48.75/share | 2026-08-20 | [closing 8-K](https://www.sec.gov/Archives/edgar/data/801337/000119312526357758/d919931d8k.htm) |
| FBRX | $77 cash/share | 2026-08-27 | [closing 8-K](https://www.sec.gov/Archives/edgar/data/1419041/000114036126034698/ef20081182_8k.htm) |
| CRNX | $85 cash/share | 2026-09-01 | [closing 8-K](https://www.sec.gov/Archives/edgar/data/1658247/000114036126035195/ef20081409_8k.htm) |
| APGE | $135.11 cash/share | 2026-09-03 | [closing 8-K](https://www.sec.gov/Archives/edgar/data/1974640/000114036126035537/ef20081397_8k.htm) |

The ledger contains 15 active-book events across these six names. Their active positions
are zero, and `high_52wk` holds 41.511110 SAN shares from WBS. The inactive
archival `news_gated_momo` snapshot still carries FBRX; settlement intentionally
does not mutate retired books. On 2026-09-07, the settlement-order reconciler also
cancelled three FBRX sell orders (1005, 1017, 1029) that had remained pending after
the positions were settled; the audit row preserves the exact order ids. The live stale-
exposure projection then returned zero positions and zero pending orders.

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
document, the position stays open and stale; that is the honest state.

## 2. Dry-run (default; opens the store read-only)

Run from the repo root. The dry run prints a before/after table per book and refuses if
the ticker has a bar with volume > 0 on or after `--effective`, if `--source` is missing,
or if the acquirer has no stored prices.

```bash
# Cash deal: every holder receives qty × price on the effective date.
.venv/bin/python -m sim.settle --db store/market.duckdb --ticker EA \
    --kind cash --price <PRICE> --effective <YYYY-MM-DD> \
    --source "<EDGAR URL of closing 8-K or press release>"

.venv/bin/python -m sim.settle --db store/market.duckdb --ticker TALK \
    --kind cash --price <PRICE> --effective <YYYY-MM-DD> --source "<URL>"

.venv/bin/python -m sim.settle --db store/market.duckdb --ticker WBS \
    --kind cash --price <PRICE> --effective <YYYY-MM-DD> --source "<URL>"

.venv/bin/python -m sim.settle --db store/market.duckdb --ticker FBRX \
    --kind cash --price <PRICE> --effective <YYYY-MM-DD> --source "<URL>"
```

Other shapes, same flags otherwise:

```bash
# Stock-for-stock: R acquirer shares per held share. Acquirer must have real bars.
... --kind stock --into <ACQ> --ratio <R>
# Mixed: R shares plus cash per share.
... --kind stock --into <ACQ> --ratio <R> --price <CASH_PER_SHARE>
# Cancelled / bankrupt: position to zero, no cash.
... --kind worthless
# Only some books (default is every active holder):
... --portfolio high_52wk,low_vol
# Free-text context that goes into the ledger row:
... --note "Cash election; CVR ignored (not priced)"
```

`--effective` is the date the terms took effect. The engine checks the ticker printed no
volume on or after it. For EA the last real trade was 2026-08-04, so `--effective` must
be 2026-08-05 or later; use the date from the filing, not the last-trade date.

## 3. Apply

Only after the dry-run table is what the filing says. Not while the nightly is running
(22:30 UTC weekdays) or a farm job holds the writer lock; `db.connect` retries the lock
for 60 s then fails, which is fine.

```bash
.venv/bin/python -m sim.settle --db store/market.duckdb --ticker EA \
    --kind cash --price <PRICE> --effective <YYYY-MM-DD> --source "<URL>" --apply
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

## 2026-10-08 — P22 lifecycle round 2 (binding orchestrator rulings)

Deploy no earlier than Sunday 2026-10-18, with parameterized D0 2026-10-19,
after lifecycle regressions and the store-copy rehearsal pass. The integration
orchestrator owns the P15 re-pin; this lane leaves its revision unchanged.

1. Accounts are independently funded. Remove the shared gross exposure cap and
   its refusal. Keep each account's default 1.0× gross limit (maximum 1.5×),
   rechecked using marks observable at the fill timestamp. Concentration remains
   an alert only; aggregate 1%-of-MDV60 liquidity follows global receipt order.
2. Use one source-aware valuation in settlement, late settlement, margin and API
   reads. Carry the last observed price, falling back to a fill, and flag it stale.
   Refuse with a reason only when no price was ever observed; never erase a liability.
3. Reconcile money within $0.005 per account and align financing/fill event order.
   Exact floating-point hashes do not decide reconciliation.
4. Halt/cancel do not attach market stores. Source reads retry writer contention
   with backoff and defer only dependent accounts with a logged reason.
5. Captured corporate actions change signed positions, lots, orders and replay,
   independently of operational prices coverage. Account dividends transact with
   account settlement; legacy reruns and dividend processing exclude accounts.
6. Late settlement processes every unresolved session oldest-first, refreshes
   carried marks without requiring a fill, and recomputes dependent later state,
   verification, halts and maintenance.
7. A contingent close cannot exceed its requested quantity, parent fill or holdings.
   Borrow and margin interest continue during retirement until flat.
8. The late CLI exits nonzero on any account error. Migration preserves v1 league
   routing, reports proposed route changes and requires --allow-routing-change
   before changing any route.


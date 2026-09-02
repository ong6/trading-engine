# Settlement runbook — dead positions

Four held names have stopped trading. The engine will never sell them (no tradeable bar)
and marks them at their last close forever; `data/reports/league.md` lists them under
"Stale marks". The engine does not know, and must not guess, what happened to them
(honesty rule 1: never invent a price). **You look up the terms; `sim/settle.py` books
exactly what you cite.**

| Ticker | Last real trade | Held by (qty, as of 2026-09-02) |
|---|---|---|
| EA | 2026-08-04 | high_52wk 7.4335, low_vol 6.1946 |
| TALK | 2026-08-14 | high_52wk 298.8506 |
| WBS | 2026-08-19 | high_52wk 20.202 |
| FBRX | 2026-08-26 | ew_benchmark 10.1828, momo_stopped 50.4191, template_top10_banded 42.7027, template_top10_banded_gated 42.7027, news_gated_momo 44.7129 |

Nothing below has been run with `--apply`. Every price and date in the commands is a
**placeholder you replace** after looking up the terms.

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
cd ~/trading-engine

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
position set to 0 (or converted). `prices` and `sim_equity` are not touched.

## 4. Verify

```bash
.venv/bin/python - <<'EOF'
import duckdb
c = duckdb.connect('store/market.duckdb', read_only=True)
print(c.execute("SELECT portfolio_id, ticker, kind, qty, price, into_ticker, ratio, "
                "effective, source FROM sim_settlements ORDER BY created_at").fetchall())
print(c.execute("SELECT portfolio_id, ticker, qty FROM sim_positions "
                "WHERE ticker IN ('EA','TALK','WBS','FBRX') AND qty > 0").fetchall())
EOF
```

The second query should be empty for every settled name. After the next nightly step
the name is gone from the "Stale marks" table in `data/reports/league.md`, and each
book's equity moves from the frozen mark to the settlement value.

`.venv/bin/python -m pytest -q tests/test_settle.py` covers the arithmetic, the
refusals, and rebuild/rerun survival.

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
- **Stock conversions carry basis.** The acquirer lot's avg_cost is the dead lot's
  avg_cost ÷ ratio, merged into any existing acquirer lot; no P&L is realised on the swap.
- **Re-settling.** A `(portfolio, ticker, effective)` primary key blocks a duplicate row.
  Settling a name a book no longer holds is refused (nothing to do), so re-running an
  applied command exits 2 rather than double-crediting.
- **Inactive books** are skipped: `holders` only considers `portfolios.active = TRUE`.

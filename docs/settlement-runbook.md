# Settlement runbook — dead positions

When a held name stops trading, the engine cannot sell it (there is no tradeable bar) and
marks it at its last close; `data/reports/league.md` lists it under "Stale marks". The
engine does not know, and must not guess, a deal price (honesty rule 1: never invent a
price). **You look up the terms; `sim/settle.py` books exactly what you cite.** If nobody
does, the engine closes the holding out at its last real traded close (owner decision
2026-10-15; next section).

## Automatic close-out of a delisted holding

Every active book type closes out a delisted holding through the same `sim_settlements`
row and replay path: the league day-step (phase a1, before fills), each P15 window (before
that session's P15 fills; the open rule closes and pending intents for the name are
cancelled) and each account fold. Retired books are not touched. A holding is delisted on
session `d` when both hold, using only data dated on or before `d`:

1. The exchange directory dropped it: its latest `universe_snapshot` row is inactive, and
   that omission began on or after its last traded bar. A name dropped while it still
   traded is never closed out automatically (BURU and ISSC were, and traded again).
2. It has printed no traded bar (the store's `REAL_BAR_SQL`, which needs a positive open, high
   and low; a zero-open quote like WBD's 40 shares on 2026-10-05 is not one) for 5 sessions.

The settlement is `cash` at that last traded close, effective the next session, with a
`source` beginning `delisting close-out:` that records the evidence. If a sourced
settlement for the ticker effective after its last trade already exists (you booked the
deal for other books), its terms are used instead. A name that never traded is left
carried. Five sessions: on the 2026-10-15 store copy no dropped name traded again after
3 silent sessions (the longest that did was AVB, 2), and it gives you a trading week to
book sourced terms first; the booked amount does not depend on it.

On the 2026-10-15 snapshot this closes out WBD in `high_52wk`: 42.922218 shares at
$30.94 (last traded 2026-10-02), effective 2026-10-05, +$1,328.01 cash against a frozen
mark of $1,328.44 at the zero-open quote's close.

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
document, book nothing: the automatic close-out above settles it at its last traded close.

## 2. Dry-run (default; opens the store read-only)

Run from the repo root. The dry run prints a before/after table per book and refuses if
the ticker has a traded bar on or after `--effective`, if `--source` is missing, or if
the acquirer has no stored prices.

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


## P22 deployment and rollback (revision 14, D0 2026-10-19)

Deploy Sunday 2026-10-18 from 19:10 UTC, after the 16:00 go/no-go accepts the exact source,
both timezone suites and the fresh-store rehearsal. Run the blocks below in one Bash shell.
The development lane executes them only in its isolated rehearsal; the orchestrator owns the
production checkout and services. Reserve space for the verified backup, incident DB/WAL/data
and published snapshot before starting. Recheck Sunday's source, snapshot and writer state.

```bash
set -euo pipefail
P22_ROOT="$(realpath "$HOME/trading-engine")"
P22_STATE="$HOME/p22-deploy-20261018"
P22_D0=2026-10-19
: "${P22_APPROVED_SHA:?Set the full deploy commit accepted by the orchestrator}"
mkdir -m 700 -p "$P22_STATE"
P22_STATE="$(realpath "$P22_STATE")"
P22_BACKUP="$P22_STATE/predeploy-bundle"
export P22_ROOT P22_STATE P22_BACKUP P22_D0
cd "$P22_ROOT"
git rev-parse HEAD > "$P22_STATE/predeploy.sha"
git status --porcelain=v1 > "$P22_STATE/predeploy.git-status"
git diff --binary > "$P22_STATE/predeploy.diff"
git show HEAD:server/p15-registration.json > "$P22_STATE/predeploy-registration.json"
.venv/bin/python --version > "$P22_STATE/predeploy-python.txt"
node --version > "$P22_STATE/predeploy-node.txt"
cp -a uv.lock pyproject.toml engine/requirements.txt ui/package.json ui/package-lock.json \
  "$P22_STATE/"
if crontab -l > "$P22_STATE/predeploy.crontab"; then
  touch "$P22_STATE/had-crontab"
fi
cp -a "$HOME/.config/systemd/user" "$P22_STATE/predeploy-units"
# Include installed inactive units and loaded activating oneshots. Private-alpha timers
# are discovered through their triggered service's ExecStart, without naming a strategy.
.venv/bin/python - <<'PY'
import json, os, subprocess
from pathlib import Path
state = Path(os.environ['P22_STATE'])
def output(*args):
    return subprocess.check_output(['systemctl', '--user', *args], text=True)
names = set()
for cmd in ('list-unit-files', 'list-units'):
    for line in output(cmd, '--all', '--no-legend', '--plain', '--no-pager').splitlines():
        fields = line.split()
        if fields and fields[0].endswith(('.service', '.timer')):
            names.add(fields[0])
properties = {}
for name in sorted(names):
    raw = output('show', name, '--property=Id,LoadState,ActiveState,SubState,UnitFileState,ExecStart,Triggers,MainPID,ControlGroup')
    properties[name] = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
managed = {name for name, p in properties.items() if
           name.startswith(('trading-engine-', 'massive-')) or
           name in {'te-autopush.service', 'te-autopush.timer', 'trading-data-backup.service',
                    'trading-data-backup.timer', 'store-sync.service', 'store-sync.timer'} or
           '/trading-alpha/' in p.get('ExecStart', '')}
managed |= {name for name, p in properties.items()
            if set(p.get('Triggers', '').split()) & managed}
records = {name: properties[name] for name in sorted(managed)}
(state / 'unit-state.json').write_text(json.dumps(records, indent=2) + '\n')
for kind in ('timer', 'service'):
    selected = [n for n in records if n.endswith('.' + kind)]
    (state / ('managed-' + kind + 's')).write_text(''.join(n + '\n' for n in selected))
    active = [n for n in selected if records[n]['ActiveState'] in {'active', 'activating', 'reloading'}]
    (state / ('resume-' + kind + 's')).write_text(''.join(n + '\n' for n in active))
PY

p22_quiesce() {
  crontab -r 2>/dev/null || test ! -f "$P22_STATE/had-crontab"
  # Stop current services as well as their timers: autopush can rebase without opening DB.
  xargs -r systemctl --user stop < "$P22_STATE/managed-timers"
  xargs -r systemctl --user stop < "$P22_STATE/managed-services"
  for P22_UNIT in trading-engine-accounts-settle.timer massive-options-daily.timer \
      trading-engine-accounts-settle.service massive-options-daily.service; do
    if test "$(systemctl --user show "$P22_UNIT" --property=LoadState --value)" != not-found; then
      systemctl --user stop "$P22_UNIT"
    fi
  done
  .venv/bin/python - <<'PY'
import json, os, subprocess
from pathlib import Path
records = json.loads((Path(os.environ['P22_STATE']) / 'unit-state.json').read_text())
for name in records:
    raw = subprocess.check_output(['systemctl', '--user', 'show', name,
                                  '--property=ActiveState,MainPID,ControlGroup'], text=True)
    p = dict(line.split('=', 1) for line in raw.splitlines())
    assert p['ActiveState'] in {'inactive', 'failed'} and p['MainPID'] == '0', (name, p)
    group = p.get('ControlGroup', '')
    procs = Path('/sys/fs/cgroup' + group) / 'cgroup.procs' if group else None
    assert procs is None or not procs.exists() or not procs.read_text().strip(), name
jobs = subprocess.check_output(['systemctl', '--user', 'list-jobs', '--no-legend', '--no-pager'], text=True)
assert not any(name in jobs for name in records), jobs
PY
  # Inventory cron-launched drivers and their child groups. A survivor means defer the
  # deploy; do not kill arbitrary processes or infer idleness from a closed DB handle.
  ps -eo pid,ppid,args > "$P22_STATE/quiesced-processes.txt"
  if pgrep -af 'run_daily\.sh|run_weekly_walkforward\.sh|run_weekly_liquidity\.sh|run_weekend_sweep\.sh|engine\.queue_runner|engine\.sync|trading-alpha/|te-autopush|tools\.free_massive_options|engine\.free_massive_minute' \
      | awk '$0 !~ /pgrep -af/ {found=1; print} END {exit !found}'; then
    return 1
  fi
  # Include the continuous Massive minute store, options/PIT stores and every WAL.
  mapfile -d '' P22_STORES < <(find store -type f \( -name '*.duckdb' -o -name '*.duckdb.wal' \) -print0)
  if ((${#P22_STORES[@]})) && fuser "${P22_STORES[@]}"; then return 1; fi
}
p22_quiesce
# Save source-dependent outputs and controls even when they are untracked/generated.
mkdir -m 700 "$P22_STATE/predeploy-artifacts"
cp -a data logs "$P22_STATE/predeploy-artifacts/"
mkdir -m 700 "$P22_STATE/predeploy-snapshot-identity"
readlink store/snapshots/market-latest.duckdb > "$P22_STATE/predeploy-snapshot-identity/latest-link"
cp -a store/snapshots/*.json "$P22_STATE/predeploy-snapshot-identity/"
.venv/bin/python -m tools.backup_database create "$P22_BACKUP" --source store/market.duckdb
.venv/bin/python -m tools.backup_database verify "$P22_BACKUP"

git pull --ff-only origin main
test "$(git rev-parse HEAD)" = "$P22_APPROVED_SHA"
.venv/bin/python -c 'import json; assert json.load(open("server/p15-registration.json"))["registration_revision"] == 14'
.venv/bin/python -m pytest -q -W error tests/test_p15_registration.py
# Migrations reproduce their deployed predecessor records and must precede any cost break.
.venv/bin/python -m farm.experiment_runner --migrate-runtime-contract
.venv/bin/python -m engine.forward_review --migrate-runtime-contract
.venv/bin/python -m engine.xs_forward_review --migrate-runtime-contract
.venv/bin/python -m tools.migrate_cost_profiles --db store/market.duckdb --d0 "$P22_D0" --apply
# Required: routing_changes [], one revision-14 break for every old portfolio, no D0 equity.
# Refresh ordinary evidence twice while readers and triggers remain stopped.
for P22_REVIEW in 1 2; do
  .venv/bin/python -m farm.experiment_runner --report-only
  .venv/bin/python -m engine.forward_review
  .venv/bin/python -m engine.xs_forward_review
done
.venv/bin/python -m server.agent_evaluation_reporting
.venv/bin/python -m tools.publish_snapshot --source store/market.duckdb
install -m 0644 server/trading-engine-accounts-settle.service \
  server/trading-engine-accounts-settle.timer server/massive-options-daily.service \
  server/massive-options-daily.timer "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
# Reopen saved API/UI readers first (UI builds on start), then verify semantics before writers.
awk '$0 ~ /^trading-engine-(api|ui)\.service$/' "$P22_STATE/resume-services" \
  | xargs -r systemctl --user start
curl --fail --silent --retry 10 --retry-connrefused --retry-delay 1 http://127.0.0.1:8000/health
curl --fail --silent http://127.0.0.1:8000/meta > "$P22_STATE/deployed-meta.json"
.venv/bin/python - <<'PY'
import json, os
from pathlib import Path
from engine import forward_review, xs_forward_review
from engine.lib import db
from farm import experiment_runner
p = json.loads((Path(os.environ['P22_STATE']) / 'deployed-meta.json').read_text())
d0 = os.environ['P22_D0']
for key, monitor, years in [('forward_review', forward_review, 1), ('xs_forward_review', xs_forward_review, 5)]:
    status = p[key]
    assert status['status'] == 'ACCUMULATING' and status['shared_sessions'] == 0 and not status['mature'], status
    assert status['runtime_contract_version'] == monitor.RUNTIME_CONTRACT_VERSION, status
    assert status['runtime_contract_sha256'] == monitor.EXPECTED_RUNTIME_CONTRACT_SHA256, status
    assert status['eligible_after'] == str(int(d0[:4]) + years) + d0[4:], status
assert p['e1_forward']['status'] == 'ACCUMULATING', p['e1_forward']
assert p['e1_forward']['runtime_contract_version'] == experiment_runner.RUNTIME_CONTRACT_VERSION
with db.connect(read_only=True) as con:
    breaks = con.execute("SELECT portfolio_id,break_date,registration_revision FROM sim_book_breaks WHERE kind='cost_profile'").fetchall()
    assert len(breaks) == con.execute('SELECT COUNT(*) FROM portfolios').fetchone()[0]
    assert all(str(day) == d0 and revision == 14 for _, day, revision in breaks)
    assert con.execute("SELECT COUNT(*) FROM portfolio_accounts_v WHERE pa_engine<>'league'").fetchone()[0] == 0
    assert con.execute('SELECT COUNT(*) FROM sim_equity WHERE date>=?', [d0]).fetchone()[0] == 0
print('semantic status, runtime, cost clock and legacy routing accepted')
PY
curl --fail --silent http://127.0.0.1:8000/accounts > "$P22_STATE/deployed-accounts.json"
.venv/bin/python -c 'import json,os; from pathlib import Path; assert json.loads((Path(os.environ["P22_STATE"])/"deployed-accounts.json").read_text()) == []'
awk '$0 !~ /^trading-engine-(api|ui)\.service$/ && $0 != "te-autopush.service"' \
  "$P22_STATE/resume-services" | xargs -r systemctl --user start
xargs -r systemctl --user start < "$P22_STATE/resume-timers"
systemctl --user enable --now trading-engine-accounts-settle.timer massive-options-daily.timer
if test -f "$P22_STATE/had-crontab"; then crontab "$P22_STATE/predeploy.crontab"; fi
# Restart autopush only if it was active; its saved timer will fire normally otherwise.
if grep -qx te-autopush.service "$P22_STATE/resume-services"; then systemctl --user start te-autopush.service; fi
```

Persistent new timers can run immediately; account for those writers before reopening triggers.
A failed semantic assertion keeps the deployment closed. The ordinary refresh does not change
old outcomes. Missing/invalid research evidence remains visible and is not an acceptance waiver.
Authenticated private-alpha account creation and cutover follow the private instructions only
after engine acceptance; the rehearsal uses synthetic accounts on captured bars.

Rollback repeats the same quiescence and archives the entire failed deployment before replacing
anything. Keep post-deploy receipts, fills, reports, controls and snapshot identity for incident
reconciliation. Source rollback does not rewind separate PIT capture stores; preserve them if
this deployment changed them. If no verified backup exists, do not enter the restore block.

```bash
cd "$P22_ROOT"
p22_quiesce
mkdir -m 700 "$P22_STATE/incident"
cp -a store/market.duckdb data logs "$P22_STATE/incident/"
if test -f store/market.duckdb.wal; then cp -a store/market.duckdb.wal "$P22_STATE/incident/"; fi
mkdir -m 700 "$P22_STATE/incident/snapshot-identity"
readlink store/snapshots/market-latest.duckdb > "$P22_STATE/incident/snapshot-identity/latest-link"
cp -a store/snapshots/*.json "$P22_STATE/incident/snapshot-identity/"
if test -f store/agent-shadow-control.json; then cp -a store/agent-shadow-control.json "$P22_STATE/incident/"; fi
.venv/bin/python -m tools.backup_database verify "$P22_BACKUP"
cp "$P22_BACKUP/market.duckdb" store/market.duckdb.restore
cmp "$P22_BACKUP/market.duckdb" store/market.duckdb.restore
rm -f store/market.duckdb.wal
mv store/market.duckdb.restore store/market.duckdb
# Generated paths can obstruct checkout. Their full bytes are now in the incident archive;
# inspect the saved status/diff, remove only these generated directories, and refuse any
# unexplained source edit. Never reset unarchived source or unknown untracked files.
rm -rf data logs
mkdir data logs
# Restore tracked generated paths to the deployed HEAD solely to permit the source checkout.
git restore --source=HEAD --worktree -- data
git checkout --detach "$(cat "$P22_STATE/predeploy.sha")"
cp -a "$P22_STATE/predeploy-artifacts/data/." data/
cp -a "$P22_STATE/predeploy-artifacts/logs/." logs/
# Restore every manifest record, including logs/friday-postflight.json and optional controls.
.venv/bin/python - <<'PY'
import hashlib, json, os, shutil
from pathlib import Path
root, bundle = Path(os.environ['P22_ROOT']), Path(os.environ['P22_BACKUP'])
manifest = json.loads((bundle / 'manifest.json').read_text())
for section in ('prospective_evidence', 'operational_artifacts', 'operational_controls'):
    for relative, record in manifest.get(section, {}).items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundle / record['bundle_path'], target)
        assert hashlib.sha256(target.read_bytes()).hexdigest() == record['sha256'], relative
PY
systemctl --user disable trading-engine-accounts-settle.timer massive-options-daily.timer
rm -f "$HOME/.config/systemd/user/trading-engine-accounts-settle.service" \
  "$HOME/.config/systemd/user/trading-engine-accounts-settle.timer" \
  "$HOME/.config/systemd/user/massive-options-daily.service" \
  "$HOME/.config/systemd/user/massive-options-daily.timer"
cp -a "$P22_STATE/predeploy-units/." "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
cmp "$P22_BACKUP/market.duckdb" store/market.duckdb
# Quarantine the v2 pointer and publish a verified restored-schema snapshot before readers.
mv store/snapshots "$P22_STATE/incident/quarantined-snapshots"
.venv/bin/python -m tools.publish_snapshot --source store/market.duckdb
.venv/bin/python - <<'PY'
import json
from engine.lib import db
from engine.lib.snapshots import latest_snapshot
from server import agent_evaluation
from datetime import datetime, timezone
assert json.load(open('server/p15-registration.json'))['registration_revision'] == 13
assert latest_snapshot(db.DEFAULT_DB, newer_than_database=True) is not None
with db.connect(read_only=True) as con:
    agent_evaluation.validate_p15_evidence(con, generated_at=datetime.now(timezone.utc))
PY
.venv/bin/python -m pytest -q -W error tests/test_p15_registration.py
awk '$0 ~ /^trading-engine-(api|ui)\.service$/' "$P22_STATE/resume-services" \
  | xargs -r systemctl --user start
curl --fail --silent --retry 10 --retry-connrefused --retry-delay 1 http://127.0.0.1:8000/health
curl --fail --silent http://127.0.0.1:8000/meta > "$P22_STATE/restored-meta.json"
.venv/bin/python - <<'PY'
import json, os
from pathlib import Path
p = json.loads((Path(os.environ['P22_STATE']) / 'restored-meta.json').read_text())
assert all(p[key]['status'] == 'ACCUMULATING' for key in ('forward_review', 'xs_forward_review', 'e1_forward'))
assert [p[k]['runtime_contract_version'] for k in ('forward_review', 'xs_forward_review', 'e1_forward')] == [10, 21, 6]
PY
cmp "$P22_BACKUP/market.duckdb" store/market.duckdb
awk '$0 !~ /^trading-engine-(api|ui)\.service$/ && $0 != "te-autopush.service"' \
  "$P22_STATE/resume-services" | xargs -r systemctl --user start
# Restore saved active/activating services and timers; inactive/disabled units stay so.
xargs -r systemctl --user start < "$P22_STATE/resume-timers"
if test -f "$P22_STATE/had-crontab"; then crontab "$P22_STATE/predeploy.crontab"; fi
```

The saved unit configuration restores prior enabled/disabled links; `unit-state.json` retains
active, activating, substate and enabled state for comparison after restoration. An interrupted
activating oneshot is restarted from its own unit entrypoint. Check every saved active target
and enabled state before closing the incident. Keep autopush stopped after a detached emergency
rollback until the orchestrator reconciles `main` or fixes forward; this is the one intentional
exception to immediate prior-state restoration. A forced writer-contention API probe in the
isolated rehearsal must use the restored snapshot and v13 forward records before producers
resume. Production does not create a contention writer as part of the deployment.

## P22 deploy/rollback rehearsal — 2026-10-08

The published `market-latest.duckdb` was copied once into the lifecycle lane. The verified
backup contains 91 tables, nine prospective evidence files and seven operational artifacts.
The lane's league reports were regenerated from the copy through a read-only connection so
its backup metadata describes that exact snapshot. Paths below are shortened to `$REHEARSAL_ROOT`,
`$BACKUP`, `$EVIDENCE` and `$XDG_RUNTIME_DIR`. The transcript combines successful backup creation
with the complete deployment/rollback run using that same verified backup.

Round 4 extended this evidence with two [retained transcripts](history/p22-round4-rehearsals.md).
`rehearsal-legacy.txt` used a disposable October 2 checkpoint and temporary October 5 D0:
all 33 routes and pre-D0 equity checkpoints stayed unchanged, pre-D0 fills kept zero fees,
and the October 5–7 legacy and P15 sessions paid the new fees and passed P15 validation.
`rehearsal-rollback.txt` restored the complete pre-migration store byte for byte and ran
revision 13 from `origin/main` (`bc6ff7d`), including HTTP health/meta, restored-store P15
validation and all five registration tests. It removed its isolated processes and copies.
The earlier transcript below covers runtime unit installation and writer quiescence; its
`b3cba65` source check is supplemented by round 4's explicit revision-13 rollback proof.

The rehearsal installed namespaced runtime units with `systemctl --user link --runtime` and
validated their rendered paths with `systemd-analyze --user verify`. The API listened on
loopback port 18022; all store paths pointed into the disposable lane directory. A receipt clock
selected the captured October 6 and 7 sessions; SPY bars came from the snapshot. D0 remained
parameterized as October 19. The options unit files were installed and validated; provider
capture was not invoked. A separate minute-store writer held a real DuckDB writer connection
under its own systemd unit to exercise rollback quiescence without requesting market data.

Rollback stopped the isolated timers, API, settlement and minute-store writer before copying
incident evidence or restoring. `fuser` found no remaining owner of either database. The restored
database passed `cmp` against the backup before and after an API health check running the archived
pre-deploy source at `b3cba65`. All rehearsal unit links were removed. The live store and live units
were not changed.

```text
$ tools.backup_database create BACKUP --source COPY
{
  "bundle": "$BACKUP",
  "database_sha256": "8bb08aa267b37ff73185e009527698bcfa0570a2acdec5cd1a4f524ac06e3a8f",
  "database_size_bytes": 7015772160,
  "database_snapshot_sha256": "ba9a7890a47f60b1bd203c0873c8045fb2d0f97ed4a03e2205a8d1ef6b6e653c",
  "evidence_file_count": 9,
  "manifest_sha256": "df8c984f520db268f8b8b63b225874ce31466ca9827dd97c2f52ecb1d106cabd",
  "operational_artifact_count": 7,
  "operational_control_count": 0,
  "source_database": {
    "kind": "repository-relative",
    "path": "store/p22-rehearsal/market.duckdb"
  },
  "status": "ok",
  "table_count": 91
}
resume with the successfully created backup, using its canonical path
$ tools.backup_database verify BACKUP
{
  "bundle": "$BACKUP",
  "database_sha256": "8bb08aa267b37ff73185e009527698bcfa0570a2acdec5cd1a4f524ac06e3a8f",
  "database_size_bytes": 7015772160,
  "database_snapshot_sha256": "ba9a7890a47f60b1bd203c0873c8045fb2d0f97ed4a03e2205a8d1ef6b6e653c",
  "evidence_file_count": 9,
  "manifest_sha256": "df8c984f520db268f8b8b63b225874ce31466ca9827dd97c2f52ecb1d106cabd",
  "operational_artifact_count": 7,
  "operational_control_count": 0,
  "source_database": {
    "kind": "repository-relative",
    "path": "store/p22-rehearsal/market.duckdb"
  },
  "status": "ok",
  "table_count": 91
}
$ tools.migrate_cost_profiles --db COPY --d0 2026-10-19 --apply
{"routing_changes": []}
migrated 33 portfolios at D0=2026-10-19; reserved order id 1774
migration break revisions: [(14, 33)]
$ systemctl --user start p22-rehearsal-api.service p22-rehearsal-accounts-settle.timer
{"ok":true,"status":"ok","db_readable":true}$ API receipts, account settlement and verification for two captured sessions
GET /health: 200
GET /meta: 200
POST /accounts: 200
POST /accounts/rehearsal-account/orders: 200
receipt 1775 queued
POST /accounts/rehearsal-account/orders: 200
receipt 1776 queued
{"affected_accounts":["rehearsal-account"],"carried":{},"completed":["rehearsal-account"],"errors":{},"expired":0,"filled":2,"late_settled":0,"pending":0,"recovered_marks":[],"rejected":0}
GET /accounts/rehearsal-account/results: 200
{"session": "2026-10-06", "fills": 2, "fees": 0.72, "closed_lots": 1}
{"account_id":"rehearsal-account","expected_sha256":"3754d6a72c9f787153a7433ec008353263efde254d74c0321239994fb23a6629","observed_sha256":"3754d6a72c9f787153a7433ec008353263efde254d74c0321239994fb23a6629","status":"ok"}
POST /accounts/rehearsal-account/orders: 200
receipt 1777 queued
POST /accounts/rehearsal-account/orders: 200
receipt 1778 queued
{"affected_accounts":["rehearsal-account"],"carried":{},"completed":["rehearsal-account"],"errors":{},"expired":0,"filled":2,"late_settled":0,"pending":0,"recovered_marks":[],"rejected":0}
GET /accounts/rehearsal-account/results: 200
{"session": "2026-10-07", "fills": 4, "fees": 1.44, "closed_lots": 2}
{"account_id":"rehearsal-account","expected_sha256":"5e417f95a608b83bbb0edff7cd30c78e9f1141725463455a81d273d092585a70","observed_sha256":"5e417f95a608b83bbb0edff7cd30c78e9f1141725463455a81d273d092585a70","status":"ok"}
$ start isolated minute-store writer to exercise rollback quiescence
$ rollback: stop every isolated timer and writer before preserving/restoring COPY
$ tools.backup_database verify BACKUP; restore checkpointed database
{
  "bundle": "$BACKUP",
  "database_sha256": "8bb08aa267b37ff73185e009527698bcfa0570a2acdec5cd1a4f524ac06e3a8f",
  "database_size_bytes": 7015772160,
  "database_snapshot_sha256": "ba9a7890a47f60b1bd203c0873c8045fb2d0f97ed4a03e2205a8d1ef6b6e653c",
  "evidence_file_count": 9,
  "manifest_sha256": "df8c984f520db268f8b8b63b225874ce31466ca9827dd97c2f52ecb1d106cabd",
  "operational_artifact_count": 7,
  "operational_control_count": 0,
  "source_database": {
    "kind": "repository-relative",
    "path": "store/p22-rehearsal/market.duckdb"
  },
  "status": "ok",
  "table_count": 91
}
restored database matches backup byte for byte
$ remove new settlement/options runtime units and restore pre-deploy API source
Removed $XDG_RUNTIME_DIR/systemd/user/p22-rehearsal-options-daily.timer.
Removed $XDG_RUNTIME_DIR/systemd/user/p22-rehearsal-accounts-settle.timer.
{"ok":true,"status":"ok","db_readable":true}rehearsal completed; isolated units removed; live store and units untouched
```

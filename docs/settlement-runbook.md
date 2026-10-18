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
2. It has printed no trusted bar for 5 sessions. Execution, marks and settlement evidence
   require finite positive OHLC, valid geometry and positive volume; a zero-open quote
   like WBD's 40 shares on 2026-10-05 is not one.

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
both timezone suites and the fresh-store rehearsal. Use the Bash sessions described below.
The development lane executes these blocks only in an isolated rehearsal; the orchestrator
owns production. Use Bash, paste blocks 1–3 in the same shell, and stop immediately on any
nonzero exit. Noninteractive Bash exits through the explicit error message. Open a fresh Bash
shell and paste blocks 4–5 for recovery; never repeat setup. If setup fails before `recovery-ready`,
there is no verified restore authority: keep the state directory and stopped triggers, and give
the failure to the orchestrator. Do not delete or reuse that directory.

Reserve space for the verified bundle, incident DB/WAL/data and snapshots. Sunday's approved
merge SHA, source/evidence coherence, available disk, locks and providers are execution-time gates.
No production command below belongs in a development lane outside the isolated harness.

Block 1 — new setup, quiescence and immutable recovery inventory:

```bash
set -eEuo pipefail
umask 077
P22_ROOT="$(realpath "$HOME/trading-engine")"
P22_STATE="$HOME/p22-deploy-20261018"
P22_D0=2026-10-19
: "${P22_APPROVED_SHA:?Set the full deploy commit accepted by the orchestrator}"
# A retry must use recovery, never overwrite the original identity/inventory.
mkdir -m 700 "$P22_STATE"
P22_STATE="$(realpath "$P22_STATE")"
P22_BACKUP="$P22_STATE/predeploy-bundle"
export P22_ROOT P22_STATE P22_BACKUP P22_D0 P22_APPROVED_SHA
trap 'rc=$?; trap - ERR; printf "P22 failed (exit %s). Keep triggers stopped; open a fresh Bash shell and use recovery for %s.\n" "$rc" "$P22_STATE" >&2; exit "$rc"' ERR
cd "$P22_ROOT"
# Discover once in memory; save this prior activation state only after quiescence.
P22_CRON_PRESENT=0
if P22_CRON="$(crontab -l)"; then P22_CRON_PRESENT=1; fi
P22_PROCESS_BEFORE="$(ps -eo pid,ppid,args)"
P22_UNIT_RECORDS="$(.venv/bin/python - <<'PYCODE'
import json, subprocess
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
managed = {name for name, p in properties.items() if p.get('LoadState') != 'not-found' and (
    name.startswith(('trading-engine-', 'massive-')) or
    name in {'te-autopush.service', 'te-autopush.timer', 'trading-data-backup.service',
             'trading-data-backup.timer', 'store-sync.service', 'store-sync.timer'} or
    '/trading-alpha/' in p.get('ExecStart', ''))}
managed |= {name for name, p in properties.items() if set(p.get('Triggers', '').split()) & managed}
print(json.dumps({name: properties[name] for name in sorted(managed)}, indent=2))
PYCODE
)"
export P22_UNIT_RECORDS P22_PROCESS_BEFORE
# Save the identical helper definitions for a fresh recovery shell.
cat > "$P22_STATE/functions.bash" <<'P22_FUNCTIONS'
p22_clean_source() {
  git diff --cached --exit-code
  .venv/bin/python - <<'PYCODE'
import subprocess
rows = subprocess.check_output(['git', 'status', '--porcelain=v1', '-z']).split(b'\0')
for row in filter(None, rows):
    path = row[3:].decode()
    assert row[:2] not in (b'R ', b' R', b'C ', b' C'), row
    assert path.startswith(('data/', 'logs/')), ('unexplained source/untracked change', row)
print('index clean; changes confined to archived generated paths')
PYCODE
}
p22_process_check() {
  .venv/bin/python - <<'PYCODE'
import json, os, re, subprocess
from pathlib import Path
root = os.environ['P22_ROOT']
roots = {root}
home_root = Path.home() / 'trading-engine'
if home_root.resolve() == Path(root):
    roots.add(str(home_root))
pattern = re.compile(r'run_daily\.sh|run_weekly_walkforward\.sh|run_weekly_liquid\.sh|run_weekend_sweeps\.sh|run_weekly_verify\.sh|tools\.verify_friday_postflight|engine\.collect|engine\.verify_prices|engine\.queue_runner|engine\.sync|store-sync|trading-alpha/|te-autopush|tools\.free_massive_options|tools\.free_sources|tools\.free_massive_minute|engine\.free_massive_minute')
def parse(text):
    rows = {}
    for line in text.splitlines():
        fields = line.split(None, 2)
        if len(fields) == 3 and fields[0].isdigit():
            rows[int(fields[0])] = (int(fields[1]), fields[2])
    return rows
def selected(rows):
    found = set()
    for pid, (_, command) in rows.items():
        try:
            cwd = str(Path(f'/proc/{pid}/cwd').resolve(strict=True))
        except (OSError, RuntimeError):
            cwd = ''
        if pattern.search(command) and (any(r in command for r in roots) or cwd == root or cwd.startswith(root + '/')):
            found.add(pid)
    while True:
        children = {pid for pid, (parent, _) in rows.items() if parent in found}
        if children <= found:
            return found
        found |= children
current = parse(subprocess.check_output(['ps', '-eo', 'pid,ppid,args'], text=True))
before = parse(os.environ.get('P22_PROCESS_BEFORE', ''))
# Preserve descendants from the tree saved before stopping units, even if reparented.
found = selected(current) | (selected(before) & current.keys())
# The executing shell and its ancestors are operators, not driver processes.
pid = os.getpid()
while pid in current:
    found.discard(pid)
    pid = current[pid][0]
for pid in sorted(found):
    print(pid, *current[pid], flush=True)
assert not found, 'producer or saved descendant survives; defer without mutation'
PYCODE
}
p22_no_db_owner() {
  mapfile -d '' P22_STORES < <(find store -type f \( -name '*.duckdb' -o -name '*.duckdb.wal' \) -print0)
  if ((${#P22_STORES[@]})) && fuser "${P22_STORES[@]}"; then return 1; fi
}
p22_autopush_held() {
  for P22_UNIT in te-autopush.timer te-autopush.service; do
    test "$(systemctl --user show "$P22_UNIT" --property=ActiveState --value)" != active
    test "$(systemctl --user show "$P22_UNIT" --property=ActiveState --value)" != activating
  done
}
p22_quiesce() {
  if crontab -l >/dev/null 2>&1; then crontab -r; fi
  printf '%s\n' "$P22_UNIT_RECORDS" | .venv/bin/python -c 'import json,sys; print("\n".join(n for n in json.load(sys.stdin) if n.endswith(".timer")))' | xargs -r systemctl --user stop
  printf '%s\n' "$P22_UNIT_RECORDS" | .venv/bin/python -c 'import json,sys; print("\n".join(n for n in json.load(sys.stdin) if n.endswith(".service")))' | xargs -r systemctl --user stop
  for P22_UNIT in trading-engine-accounts-settle.timer massive-options-daily.timer \
      trading-engine-accounts-settle.service massive-options-daily.service; do
    if test "$(systemctl --user show "$P22_UNIT" --property=LoadState --value)" != not-found; then
      systemctl --user stop "$P22_UNIT"
    fi
  done
  .venv/bin/python - <<'PYCODE'
import json, os, subprocess
from pathlib import Path
names = set(json.loads(os.environ['P22_UNIT_RECORDS'])) | {
    'trading-engine-accounts-settle.timer', 'massive-options-daily.timer',
    'trading-engine-accounts-settle.service', 'massive-options-daily.service'}
for name in names:
    raw = subprocess.check_output(['systemctl', '--user', 'show', name,
        '--property=ActiveState,MainPID,ControlGroup'], text=True)
    props = dict(line.split('=', 1) for line in raw.splitlines())
    assert props['ActiveState'] in {'inactive', 'failed'} and props.get('MainPID', '0') == '0', (name, props)
    group = props.get('ControlGroup', '')
    procs = Path('/sys/fs/cgroup' + group) / 'cgroup.procs' if group else None
    assert procs is None or not procs.exists() or not procs.read_text().strip(), name
jobs = subprocess.check_output(['systemctl', '--user', 'list-jobs', '--no-legend', '--no-pager'], text=True)
assert not any(name in jobs for name in names), jobs
PYCODE
  p22_process_check
  p22_no_db_owner
  p22_autopush_held
}
p22_lock() {
  mapfile -t P22_LOCKS < <(.venv/bin/python -c 'from tools.backup_database import LOCK_FILES; print("\n".join(LOCK_FILES))')
  P22_LOCK_FDS=()
  for P22_LOCK in "${P22_LOCKS[@]}"; do
    test ! -L "$P22_LOCK"
    mkdir -p "$(dirname "$P22_LOCK")"
    exec {P22_FD}>>"$P22_LOCK"
    P22_LOCK_FDS+=("$P22_FD")
    flock -n "$P22_FD" || return 1
  done
  printf 'producer locks held: %s\n' "${P22_LOCKS[*]}"
}
p22_unlock() {
  for P22_FD in "${P22_LOCK_FDS[@]}"; do eval "exec ${P22_FD}>&-"; done
  P22_LOCK_FDS=()
}
p22_http_200() {
  timeout 60 bash -c '
    for attempt in {1..30}; do
      code=$(curl --silent --output /dev/null --write-out "%{http_code}" --connect-timeout 2 --max-time 3 "$1") || code=000
      if test "$code" = 200; then printf "%s HTTP 200\n" "$1"; exit 0; fi
      sleep 1
    done
    exit 1' bash "$1"
}
p22_readers_ready() {
  systemctl --user start --no-block trading-engine-api.service trading-engine-ui.service
  p22_http_200 http://127.0.0.1:8000/health
  p22_http_200 http://127.0.0.1:3000/
  p22_http_200 http://127.0.0.1:3000/api/health
  systemctl --user is-active --quiet trading-engine-api.service
  systemctl --user is-active --quiet trading-engine-ui.service
  p22_autopush_held
}
p22_release_producers() {
  awk '$0 !~ /^trading-engine-(api|ui)\.service$/ && $0 != "te-autopush.service"' \
    "$P22_STATE/resume-services" | xargs -r systemctl --user start --no-block
  awk '$0 != "te-autopush.timer"' "$P22_STATE/resume-timers" | xargs -r systemctl --user start
  if test -f "$P22_STATE/had-crontab"; then crontab "$P22_STATE/predeploy.crontab"; fi
  p22_autopush_held
}
P22_FUNCTIONS
source "$P22_STATE/functions.bash"
p22_clean_source
p22_quiesce
p22_lock
# No unit/cron/source inventory file is ever overwritten, even on recovery.
set -o noclobber
git rev-parse HEAD > "$P22_STATE/predeploy.sha"
git status --porcelain=v1 > "$P22_STATE/predeploy.git-status"
git diff --binary > "$P22_STATE/predeploy.diff"
git show HEAD:server/p15-registration.json > "$P22_STATE/predeploy-registration.json"
printf '%s\n' "$P22_ROOT" > "$P22_STATE/root"
printf '%s\n' "$P22_D0" > "$P22_STATE/d0"
printf '%s\n' "$P22_UNIT_RECORDS" > "$P22_STATE/unit-state.json"
printf '%s\n' "$P22_PROCESS_BEFORE" > "$P22_STATE/pre-stop-processes.txt"
printf '%s\n' "$P22_CRON" > "$P22_STATE/predeploy.crontab"
if test "$P22_CRON_PRESENT" = 1; then touch "$P22_STATE/had-crontab"; fi
.venv/bin/python --version > "$P22_STATE/predeploy-python.txt"
node --version > "$P22_STATE/predeploy-node.txt"
cp -a uv.lock pyproject.toml engine/requirements.txt ui/package.json ui/package-lock.json "$P22_STATE/"
cp -a "$HOME/.config/systemd/user" "$P22_STATE/predeploy-units"
.venv/bin/python - <<'PYCODE'
import json, os, shutil
from pathlib import Path
state = Path(os.environ['P22_STATE'])
records = json.loads(os.environ['P22_UNIT_RECORDS'])
for kind in ('timer', 'service'):
    active = [n for n in records if n.endswith('.' + kind) and records[n]['ActiveState'] in {'active', 'activating', 'reloading'}]
    (state / ('resume-' + kind + 's')).write_text(''.join(n + '\n' for n in active))
for name in ('data', 'logs'):
    shutil.copytree(name, state / 'predeploy-artifacts' / name, ignore=shutil.ignore_patterns('*.lock'))
PYCODE
mkdir -m 700 "$P22_STATE/predeploy-snapshot-identity"
readlink store/snapshots/market-latest.duckdb > "$P22_STATE/predeploy-snapshot-identity/latest-link"
cp -a store/snapshots/*.json "$P22_STATE/predeploy-snapshot-identity/"
# Backup creation takes the same producer locks itself; do not nest those locks.
p22_unlock
.venv/bin/python -m tools.backup_database create "$P22_BACKUP" --source store/market.duckdb
.venv/bin/python -m tools.backup_database verify "$P22_BACKUP"
.venv/bin/python - <<'PYCODE'
import json, os
from pathlib import Path
s = Path(os.environ['P22_STATE'])
m = json.loads((s / 'predeploy-bundle/manifest.json').read_text())
assert m['release_identity']['git_sha'] == (s / 'predeploy.sha').read_text().strip()
assert json.loads((s / 'predeploy-registration.json').read_text())['registration_revision'] == 13
PYCODE
touch "$P22_STATE/recovery-ready"
```

Block 2 — approved source, migrations, ordinary report refresh and API/UI gates:

```bash
p22_quiesce
p22_clean_source
# Generated changes are archived. Restore only these tracked paths to permit pull.
git checkout HEAD -- data
git pull --ff-only origin main
test "$(git rev-parse HEAD)" = "$P22_APPROVED_SHA"
cp -a "$P22_STATE/predeploy-artifacts/data/." data/
cp -a "$P22_STATE/predeploy-artifacts/logs/." logs/
.venv/bin/python -c 'import json; assert json.load(open("server/p15-registration.json"))["registration_revision"] == 14'
.venv/bin/python -m pytest -q -W error tests/test_p15_registration.py
.venv/bin/python -m farm.experiment_runner --migrate-runtime-contract
.venv/bin/python -m engine.forward_review --migrate-runtime-contract
.venv/bin/python -m engine.xs_forward_review --migrate-runtime-contract
.venv/bin/python -m tools.migrate_cost_profiles --db store/market.duckdb --d0 "$P22_D0" --apply
# Require routing_changes [], 33 old-book revision-14 breaks and no D0 equity.
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
p22_readers_ready
curl --fail --silent --connect-timeout 2 --max-time 60 http://127.0.0.1:8000/meta > "$P22_STATE/deployed-meta.json"
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
```

Block 3 — first persistent-timer activations, DB clearance, then explicit trigger release:

```bash
# Other producers and autopush stay stopped while the new timers first activate.
.venv/bin/python - <<'PYCODE'
import json, os, subprocess, time
from pathlib import Path
state = Path(os.environ['P22_STATE'])
result = {}
for timer in ('trading-engine-accounts-settle.timer', 'massive-options-daily.timer'):
    service = timer.removesuffix('.timer') + '.service'
    def properties():
        raw = subprocess.check_output(['systemctl', '--user', 'show', service,
            '--property=ActiveState,MainPID,Result,ExecMainStatus,ExecMainStartTimestampMonotonic,ControlGroup'], text=True)
        return dict(line.split('=', 1) for line in raw.splitlines())
    before = properties()['ExecMainStartTimestampMonotonic']
    subprocess.run(['systemctl', '--user', 'enable', '--now', timer], check=True)
    deadline = time.monotonic() + 3 * 60 * 60 + 60
    # Start explicitly if there is no pending persistent catch-up. This guarantees
    # the first activation is observed even on a host without a timer stamp.
    subprocess.run(['systemctl', '--user', 'start', '--no-block', service], check=True)
    while time.monotonic() < deadline:
        props = properties()
        if props['ActiveState'] == 'failed':
            raise RuntimeError((service, props))
        if props['ExecMainStartTimestampMonotonic'] != before and props['ActiveState'] == 'inactive' and props['MainPID'] == '0':
            assert props['Result'] == 'success' and props['ExecMainStatus'] == '0', (service, props)
            group = props.get('ControlGroup', '')
            procs = Path('/sys/fs/cgroup' + group) / 'cgroup.procs' if group else None
            assert procs is None or not procs.exists() or not procs.read_text().strip(), service
            result[timer] = props
            print(service, 'first activation complete', flush=True)
            break
        time.sleep(1)
    else:
        raise TimeoutError(service)
    subprocess.run(['systemctl', '--user', 'stop', timer], check=True)
(state / 'first-activations.json').write_text(json.dumps(result, indent=2) + '\n')
PYCODE
# Close readers briefly to prove no remaining DB owner after catch-up.
systemctl --user stop trading-engine-api.service trading-engine-ui.service
p22_process_check
p22_no_db_owner
p22_readers_ready
p22_release_producers
systemctl --user start trading-engine-accounts-settle.timer massive-options-daily.timer
# Final explicit autopush release, only after every deployment gate passed.
if grep -qx te-autopush.timer "$P22_STATE/resume-timers"; then systemctl --user start te-autopush.timer; fi
if grep -qx te-autopush.service "$P22_STATE/resume-services"; then systemctl --user start --no-block te-autopush.service; fi
printf 'P22 deployment complete\n'
```

A failed or timed-out first activation is a deployment failure; enter recovery without reopening
other triggers. Inspect the service journal for a provider refusal. An exit status of zero is
required; an expected provider refusal still needs orchestrator reconciliation. The bounded
three-hour options wait matches its installed TimeoutStartSec. Ordinary refresh never waives
invalid research evidence. Private account creation/cutover follows private instructions after
engine acceptance.

Block 4 — fresh-shell recovery initializer. Load the existing state without recapturing anything:

```bash
set -eEuo pipefail
umask 077
P22_STATE="$HOME/p22-deploy-20261018"
P22_STATE="$(realpath "$P22_STATE")"
export P22_STATE
# Validate before sourcing anything or changing a file/service. An incomplete setup
# has no restore authority: preserve it and ask the orchestrator to reconcile it.
/usr/bin/python3 - <<'PYCODE'
import json, os, re, stat
from pathlib import Path
s = Path(os.environ['P22_STATE'])
assert s.is_dir() and s.stat().st_uid == os.getuid() and stat.S_IMODE(s.stat().st_mode) == 0o700
for name in ('recovery-ready', 'root', 'd0', 'predeploy.sha', 'predeploy-registration.json',
             'unit-state.json', 'pre-stop-processes.txt', 'resume-services', 'resume-timers',
             'predeploy.crontab', 'functions.bash'):
    p = s / name
    assert p.is_file() and not p.is_symlink() and p.stat().st_uid == os.getuid(), name
assert re.fullmatch(r'[0-9a-f]{40}\n', (s / 'predeploy.sha').read_text())
assert (s / 'd0').read_text().strip() == '2026-10-19'
assert json.loads((s / 'predeploy-registration.json').read_text())['registration_revision'] == 13
records = json.loads((s / 'unit-state.json').read_text())
assert records and all(re.fullmatch(r'[A-Za-z0-9_.@:-]+\.(service|timer)', n) for n in records)
for kind in ('service', 'timer'):
    expected = {n for n, p in records.items() if n.endswith('.' + kind) and p['ActiveState'] in {'active', 'activating', 'reloading'}}
    assert set((s / ('resume-' + kind + 's')).read_text().splitlines()) == expected
PYCODE
P22_ROOT="$(cat "$P22_STATE/root")"
P22_D0="$(cat "$P22_STATE/d0")"
P22_BACKUP="$P22_STATE/predeploy-bundle"
P22_UNIT_RECORDS="$(cat "$P22_STATE/unit-state.json")"
P22_PROCESS_BEFORE="$(cat "$P22_STATE/pre-stop-processes.txt")"
export P22_ROOT P22_D0 P22_BACKUP P22_UNIT_RECORDS P22_PROCESS_BEFORE
trap 'rc=$?; trap - ERR; printf "Recovery failed (exit %s); retain stopped triggers and state %s for reconciliation.\n" "$rc" "$P22_STATE" >&2; exit "$rc"' ERR
cd "$P22_ROOT"
test "$(realpath .)" = "$P22_ROOT"
git cat-file -e "$(cat "$P22_STATE/predeploy.sha")^{commit}"
.venv/bin/python -m tools.backup_database verify "$P22_BACKUP"
.venv/bin/python - <<'PYCODE'
import json, os
from pathlib import Path
s = Path(os.environ['P22_STATE'])
m = json.loads((s / 'predeploy-bundle/manifest.json').read_text())
assert m['release_identity']['git_sha'] == (s / 'predeploy.sha').read_text().strip()
PYCODE
source "$P22_STATE/functions.bash"
set -o noclobber
p22_quiesce
p22_clean_source
printf 'fresh-shell recovery initialized; original inventory preserved\n'
```

Block 5 — rollback with producer locks held through the incident archive and restoration:

```bash
p22_quiesce
p22_clean_source
p22_lock
# All producer locks remain held through incident capture, source and DB restore.
mkdir -m 700 "$P22_STATE/incident"
cp -a store/market.duckdb data logs "$P22_STATE/incident/"
if test -f store/market.duckdb.wal; then cp -a store/market.duckdb.wal "$P22_STATE/incident/"; fi
mkdir -m 700 "$P22_STATE/incident/snapshot-identity"
readlink store/snapshots/market-latest.duckdb > "$P22_STATE/incident/snapshot-identity/latest-link"
cp -a store/snapshots/*.json "$P22_STATE/incident/snapshot-identity/"
if test -f store/agent-shadow-control.json; then cp -a store/agent-shadow-control.json "$P22_STATE/incident/"; fi
.venv/bin/python -m tools.backup_database verify "$P22_BACKUP"
# Git 2.20 compatible. Refusal above precedes cleanup; checkout precedes DB replacement.
# Keep lock-file inodes while clearing archived generated paths.
find data logs -type f ! -name '*.lock' -delete
find data logs -type l -delete
git checkout HEAD -- data
git checkout --detach "$(cat "$P22_STATE/predeploy.sha")"
cp -a "$P22_STATE/predeploy-artifacts/data/." data/
cp -a "$P22_STATE/predeploy-artifacts/logs/." logs/
cp "$P22_BACKUP/market.duckdb" store/market.duckdb.restore
cmp "$P22_BACKUP/market.duckdb" store/market.duckdb.restore
rm -f store/market.duckdb.wal
mv store/market.duckdb.restore store/market.duckdb
.venv/bin/python - <<'PYCODE'
import hashlib, json, os, shutil
from pathlib import Path
root, bundle = Path(os.environ['P22_ROOT']), Path(os.environ['P22_BACKUP'])
manifest = json.loads((bundle / 'manifest.json').read_text())
for section in ('prospective_evidence', 'operational_artifacts', 'operational_controls'):
    for relative, record in manifest.get(section, {}).items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        # Write in place so existing lock-file inodes remain held.
        with target.open('wb') as out, (bundle / record['bundle_path']).open('rb') as source:
            shutil.copyfileobj(source, out)
        assert hashlib.sha256(target.read_bytes()).hexdigest() == record['sha256'], relative
PYCODE
systemctl --user disable trading-engine-accounts-settle.timer massive-options-daily.timer
rm -f "$HOME/.config/systemd/user/trading-engine-accounts-settle.service" \
  "$HOME/.config/systemd/user/trading-engine-accounts-settle.timer" \
  "$HOME/.config/systemd/user/massive-options-daily.service" \
  "$HOME/.config/systemd/user/massive-options-daily.timer"
cp -a "$P22_STATE/predeploy-units/." "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
cmp "$P22_BACKUP/market.duckdb" store/market.duckdb
mv store/snapshots "$P22_STATE/incident/quarantined-snapshots"
p22_autopush_held
p22_unlock
# Publication acquires its own locks; all triggers remain stopped.
.venv/bin/python -m tools.publish_snapshot --source store/market.duckdb
.venv/bin/python - <<'PYCODE'
import json
from engine.lib import db
from engine.lib.snapshots import latest_snapshot
from server import agent_evaluation
from datetime import datetime, timezone
assert json.load(open('server/p15-registration.json'))['registration_revision'] == 13
assert latest_snapshot(db.DEFAULT_DB, newer_than_database=True) is not None
with db.connect(read_only=True) as con:
    agent_evaluation.validate_p15_evidence(con, generated_at=datetime.now(timezone.utc))
PYCODE
.venv/bin/python -m pytest -q -W error tests/test_p15_registration.py
p22_readers_ready
curl --fail --silent --connect-timeout 2 --max-time 60 http://127.0.0.1:8000/meta > "$P22_STATE/restored-meta.json"
.venv/bin/python - <<'PYCODE'
import json, os
from pathlib import Path
p = json.loads((Path(os.environ['P22_STATE']) / 'restored-meta.json').read_text())
assert all(p[key]['status'] == 'ACCUMULATING' for key in ('forward_review', 'xs_forward_review', 'e1_forward'))
assert [p[k]['runtime_contract_version'] for k in ('forward_review', 'xs_forward_review', 'e1_forward')] == [10, 21, 6]
PYCODE
cmp "$P22_BACKUP/market.duckdb" store/market.duckdb
p22_release_producers
p22_autopush_held
printf 'P22 rollback complete; autopush timer and service held for reconciliation\n'
```

Source rollback does not rewind separate PIT stores; their changes need incident reconciliation.
The saved unit configuration restores prior enabled/disabled links and saved activating oneshots
restart from their own entrypoints. Keep the incident archive and original inventory. Both
autopush units remain stopped after detached rollback; after reconciliation use the final block.
A repeated rollback refuses the existing incident directory instead of overwriting evidence.
If recovery itself fails after source/DB restoration, retain stopped triggers and hand the
existing incident and original bundle to the orchestrator; do not rerun destructive blocks.

Block 6 — final recovery autopush release, requiring the accepted reconciled main identity:

```bash
# Run only after the orchestrator reconciles main or fixes forward.
test "$(git symbolic-ref --short HEAD)" = main
: "${P22_RECONCILED_SHA:?Set the full reconciled commit accepted by the orchestrator}"
test "$(git rev-parse HEAD)" = "$P22_RECONCILED_SHA"
p22_clean_source
p22_autopush_held
if grep -qx te-autopush.timer "$P22_STATE/resume-timers"; then systemctl --user start te-autopush.timer; fi
if grep -qx te-autopush.service "$P22_STATE/resume-services"; then systemctl --user start --no-block te-autopush.service; fi
```

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

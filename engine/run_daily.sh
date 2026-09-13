#!/usr/bin/env bash
# Nightly driver: refresh the universe, then collect the day's EOD bars.
# Calendar-gating lives inside collect.py (incremental mode exits 0 on holidays).
set -euo pipefail

# Shared preamble (engine/lib/driver.sh): resolve REPO_ROOT + cd, overlap guard
# (non-blocking flock on .nightly.lock), PY=, PYTHONUNBUFFERED, LOG=, stage
# breadcrumb, and the errexit/pipefail-safe tee wrap in driver_main.
DRIVER_NAME=run_daily
DRIVER_LOCK=.nightly.lock
DRIVER_LOCK_MSG="another run_daily is still running (lock held) — aborting this nightly"
DRIVER_LOG_PREFIX=run
DRIVER_LOG_APPEND=0   # the nightly log is truncated per day, not appended
DRIVER_STAGE_FILE=logs/.last_stage
source "$(dirname "${BASH_SOURCE[0]}")/lib/driver.sh"

body() {
  # Pull only from a configured upstream whose local tracking ref resolves.
  # Pin the remote and branch explicitly so pull.rebase/pushRemote defaults
  # cannot silently redirect unattended synchronization.
  branch="$(git symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
  remote="$(git config --get "branch.${branch}.remote" 2>/dev/null || true)"
  merge_ref="$(git config --get "branch.${branch}.merge" 2>/dev/null || true)"
  remote_branch="${merge_ref#refs/heads/}"
  upstream_ref="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || true)"
  remote_exists=0
  if [ "${remote}" = "." ]; then
    remote_exists=1
  elif [ -n "${remote}" ] && git remote get-url "${remote}" >/dev/null 2>&1; then
    remote_exists=1
  fi
  if [ -n "${branch}" ] && [ -n "${remote}" ] \
      && [ "${merge_ref}" != "${remote_branch}" ] \
      && [ "${remote_exists}" -eq 1 ] \
      && [ -n "${upstream_ref}" ] \
      && git rev-parse --verify --quiet "${upstream_ref}^{commit}" >/dev/null; then
    git pull --rebase "${remote}" "${remote_branch}" \
      || echo "WARN: git pull --rebase ${remote} ${remote_branch} failed; continuing with local state"
  else
    echo "INFO: no usable upstream configured; skipping pull"
  fi

  # universe.py raises if nasdaqtraded.txt is unreachable after retries; a stale
  # universe table (from a prior run) is fine since collect reads it from DuckDB,
  # so never let a failed refresh abort the whole nightly under set -e.
  stage universe
  "${PY}" -m engine.universe || echo "WARN: universe refresh failed; continuing with existing universe table"
  stage collect
  "${PY}" -m engine.collect   # incremental daily (calendar-gated)

  # Freeze one breadth-qualified market date for both screen and league. A
  # partial batch or stray phantom quote may remain in prices for audit, but it
  # must not advance paper state. The resolver requires >=90% of active liquid
  # names (and >=1,000 names for a production-sized universe) to have real bars.
  stage market-date
  market_date="$("${PY}" -m engine.market_date)"
  if [[ ! "${market_date}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    echo "ERROR: invalid breadth-qualified market date: ${market_date}"
    return 1
  fi
  echo "INFO: breadth-qualified market date ${market_date}"

  # rank universe + trend template, write screens/eod. --skip-if-done: on a
  # weekend/holiday run collect no-ops so market_date is already screened — no-op
  # cleanly (exit 0) instead of aborting the nightly; real failures still exit 1.
  stage screen
  "${PY}" -m engine.screen --date "${market_date}" --skip-if-done

  # --- Corporate actions: fetch, then reconcile. MUST sit between screen and
  # league, because the league steps the books against `prices` and a stored
  # scale break makes a held name look like it crashed ~(1−1/ratio) overnight.
  #
  # Fatality semantics differ between the two on purpose:
  #  * the FETCH is warn-and-continue. It is a network call, and a night with no
  #    fresh actions data is not a night with wrong data: the reconciler still
  #    adjudicates everything already stored, and the independent >40%-move
  #    tripwire fires regardless of whether the fetch succeeded. Failing the
  #    nightly on a Yahoo hiccup would cost fills and league continuity for no
  #    correctness gain.
  #  * the RECONCILE is FATAL (deliberately un-`||`-guarded under set -e). If it
  #    cannot run we do not know whether the price scale the league is about to
  #    trade on is coherent, and trading on a broken scale is strictly worse than
  #    skipping a night. Note that a skipped_sanity verdict is NOT a failure — it
  #    is the designed "never guess" outcome and surfaces as a TODO breadcrumb in
  #    this log plus an audit_log row.
  stage actions
  "${PY}" -m engine.actions --mode incremental \
    || echo "WARN: corporate-actions fetch failed (exit $?) — reconcile still runs over stored actions; the >40% move tripwire is independent of this fetch"
  stage reconcile
  "${PY}" -m engine.actions --mode reconcile

  # Paper league (exec-design §1 nightly order: … → screen → league → report → sync).
  # --init is idempotent (creates only absent portfolios); the step writes
  # data/reports/league.md + league.csv itself. --skip-if-done keeps a weekend/
  # holiday re-run (market_date unchanged) a clean exit 0; a real error still fails
  # the nightly loudly via set -e / PIPESTATUS below.
  stage league
  "${PY}" -m sim.league --date "${market_date}" --init --skip-if-done

  # Evaluate the selected strategy's frozen forward-paper kill rule. This is a
  # read-only monitor: it writes a report and never retires/promotes a book or
  # submits an order. A partial (<12 month) record stays ACCUMULATING.
  stage forward-review
  "${PY}" -m engine.forward_review \
    || echo "WARN: forward paper review failed (exit $?) — league state is unchanged"

  # Freeze and monitor raw 12-1 momentum against the screen benchmark. Until
  # both books execute their 2026-09-30 signal at the next open this writes a
  # safe WAITING report; like the sector monitor it is read-only and fail-soft.
  stage xs-forward-review
  "${PY}" -m engine.xs_forward_review \
    || echo "WARN: XS forward paper review failed (exit $?) — league state is unchanged"

  # --- E1 forward (out-of-sample) experiment record (§12.3). Milliseconds of
  # work — one SPY row per Monday — so it runs INLINE here rather than through
  # the farm queue. Position matters twice:
  #  * AFTER league, so it sits with the rest of the forward evidence;
  #  * BEFORE sync, so the regenerated report is committed the same night
  #    (the farm section runs post-sync and would miss the commit by a day).
  # Non-fatal by design: experiment reporting must NEVER block trading data.
  # On a non-Monday this is a no-op that just refreshes the report.
  stage experiment
  "${PY}" -m farm.experiment_runner --id e1-spy-monday \
    || echo "WARN: E1 forward experiment runner failed (exit $?) — no trading data" \
            "is affected; the runner is idempotent and will pick the Monday up" \
            "on the next run"

  # Sync is best-effort: a failure must NOT fail the nightly — the league/screen
  # results are already safe in DuckDB + data/ and will re-stage next nightly.
  stage sync
  "${PY}" -m engine.sync || echo "WARN: sync failed (exit $?) — league/screen results are safe in DuckDB + data/; will re-stage next nightly"

  # --- EOD price cross-check against a SECOND, independent source (Nasdaq's own
  # quote-history API). Samples ~40 names + the core ETFs + everything a league
  # book actually holds, and compares the last 5 sessions of OHLC against the
  # store. It NEVER writes a price row and NEVER corrects one: the store has a
  # single price source, and the risk it cannot see is yfinance being silently
  # WRONG (bad split adjustment, stale bar, restated close) rather than
  # yfinance being down — collect is incremental and resumable, so an outage
  # costs a day, while a bad price costs fills.
  #
  # Placement: AFTER league and sync, so it can never delay a trade or a commit,
  # and BEFORE the farm subshell, which takes the DuckDB writer for hours (this
  # stage needs a read-only handle and would otherwise wait behind it).
  #
  # Non-fatal by construction — the script itself always exits 0 (the retired news-analyst driver's
  # posture: a network failure or a source change logs a breadcrumb and leaves
  # the nightly untouched), and the `||` is belt-and-braces under set -e.
  # Its only output is the `price_verify` key of data/_meta.json, merged. That
  # key is written after sync, so it reaches git on the FOLLOWING night's commit
  # — acceptable for an observability stage; moving it earlier would put a
  # multi-minute network call in front of the league's own commit.
  stage verify-prices
  "${PY}" -m engine.verify_prices --sample 40 --sessions 5 \
    || echo "WARN: price verify exited non-zero (exit $?) — it is designed to" \
            "exit 0 on every failure path, so this means the script itself" \
            "broke; no trading data is affected"

  # --- Farm work: LOWEST priority (§12.7 — the nightly loop preempts the farm).
  # Runs AFTER sync so data collection + the committed screen/league are already
  # safe. A failure here is logged but must NOT fail the nightly: subshell pins
  # its own exit to 0 so set -e / PIPESTATUS never see it.
  (
    set +e
    echo "--- farm (post-sync, lowest priority §12.7): mining enqueue + drain ---"
    # The enqueue POLICY (intraday 100, signals 105 incremental, earnings 110,
    # fundamentals 120 on Fridays UTC) lives in engine/queue_runner.py
    # `nightly_plan` since 2026-09-03 — tested in tests/test_queue_runner.py
    # rather than expressed in bash. Every job is attempted even if one refuses.
    "${PY}" -m engine.queue_runner --enqueue-nightly
    en=$?
    # --jobs 8: `parallel_safe` kinds (walkforward, backtest, sweep) run as
    # read-only children while the parent DROPS the write lock; store-writing
    # kinds (intraday, signals, earnings, fundamentals, actions) are never
    # batched and keep the single writer to themselves. Batches form only from
    # jobs already adjacent in priority order, so the three mining jobs above
    # still run first. Without this a sweep landing in the nightly's drain pins
    # the writer for hours and the API/UI answer 503 all through the next
    # session (measured 2026-08-20: 7.5 h, load 2.9 on a 32-core box).
    # Width 4 -> 8 (2026-08-20, measured): a fixed unit of 8 identical 1-fold
    # replays ran 355 jobs/h at 4 workers x 4 threads vs 523 at 8x4 (+47%);
    # peak RSS per worker is 3.4 GB measured (declared 4.5 GB, 8 x 4.5 = 36 GB
    # inside the 48 GB engine budget), and sustained load stays ~20-24 of 32
    # cores, under the LOAD_5MIN_MAX=28 guard.
    "${PY}" -m engine.queue_runner --run --jobs 8
    rn=$?
    if [ "${en}" -ne 0 ] || [ "${rn}" -ne 0 ]; then
      echo "WARN: farm section had failures (enqueue-nightly=${en} run=${rn})" \
           "— nightly NOT failed; collect/screen/league/sync already succeeded"
    else
      echo "INFO: farm section OK (mining enqueued + queue drained)"
    fi
    exit 0
  )

}

driver_main body

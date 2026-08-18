#!/usr/bin/env bash
# Nightly driver: refresh the universe, then collect the day's EOD bars.
# Calendar-gating lives inside collect.py (incremental mode exits 0 on holidays).
set -euo pipefail

# Resolve repo root from this script's location (path-independent).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

# Overlap guard: refuse to start if a prior run_daily is still alive. The farm
# drain runs INSIDE this script, so a slow Monday drain can still hold this at
# Tuesday 22:30 — non-blocking flock on fd 9 covers the whole script body below.
exec 9>"${REPO_ROOT}/.nightly.lock"
if ! flock -n 9; then
  echo "ERROR: another run_daily is still running (lock held) — aborting this nightly"
  exit 1
fi

PY="${REPO_ROOT}/.venv/bin/python"
export PYTHONUNBUFFERED=1   # keep the tee'd log + cron.log live, not block-buffered
mkdir -p "${REPO_ROOT}/logs"
LOG="${REPO_ROOT}/logs/run-$(date +%F).log"

# Stage breadcrumb: the tee'd block below is a pipeline, so it runs in a SUBSHELL
# and its variables don't survive to the failure breadcrumb. Record the current
# stage to a small state file instead; the breadcrumb reads it back.
STAGE_FILE="${REPO_ROOT}/logs/.last_stage"
stage() { echo "$1" > "${STAGE_FILE}"; }
: > "${STAGE_FILE}"

# Everything below is teed into the daily log.
{
  echo "=== run_daily $(date -u +%FT%TZ) ==="

  # Pull latest if a git remote exists; tolerate failure (local-only is fine).
  if git remote | grep -q .; then
    git pull --rebase || echo "WARN: git pull --rebase failed; continuing with local state"
  else
    echo "INFO: no git remote configured; skipping pull"
  fi

  # universe.py raises if nasdaqtraded.txt is unreachable after retries; a stale
  # universe table (from a prior run) is fine since collect reads it from DuckDB,
  # so never let a failed refresh abort the whole nightly under set -e.
  stage universe
  "${PY}" engine/universe.py || echo "WARN: universe refresh failed; continuing with existing universe table"
  stage collect
  "${PY}" engine/collect.py   # incremental daily (calendar-gated)

  # rank universe + trend template, write screens/eod. --skip-if-done: on a
  # weekend/holiday run collect no-ops so MAX(date) is already screened — no-op
  # cleanly (exit 0) instead of aborting the nightly; real failures still exit 1.
  stage screen
  "${PY}" engine/screen.py --skip-if-done

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
  "${PY}" engine/actions.py --mode incremental \
    || echo "WARN: corporate-actions fetch failed (exit $?) — reconcile still runs over stored actions; the >40% move tripwire is independent of this fetch"
  stage reconcile
  "${PY}" engine/actions.py --mode reconcile

  # Paper league (exec-design §1 nightly order: … → screen → league → report → sync).
  # --init is idempotent (creates only absent portfolios); the step writes
  # data/reports/league.md + league.csv itself. --skip-if-done keeps a weekend/
  # holiday re-run (MAX(date) unchanged) a clean exit 0; a real error still fails
  # the nightly loudly via set -e / PIPESTATUS below.
  stage league
  "${PY}" -m sim.league --init --skip-if-done

  # --- E1 forward (out-of-sample) experiment record (§12.3). Milliseconds of
  # work — one SPY row per Monday — so it runs INLINE here rather than through
  # the farm queue. Position matters twice:
  #  * AFTER league, so it sits with the rest of the forward evidence;
  #  * BEFORE sync, so the regenerated report is committed the same night
  #    (the farm section runs post-sync and would miss the commit by a day).
  # Non-fatal by design: experiment reporting must NEVER block trading data.
  # On a non-Monday this is a no-op that just refreshes the report.
  stage experiment
  "${PY}" farm/experiment_runner.py --id e1-spy-monday \
    || echo "WARN: E1 forward experiment runner failed (exit $?) — no trading data" \
            "is affected; the runner is idempotent and will pick the Monday up" \
            "on the next run"

  # --- Agentic books: AI-vs-twin spread, applied/rejected changes, veto
  # hit-rate (agentic-strategies-design "Success / failure, pre-registered").
  # Pure render over sim_equity + agents/<book>/ state — read-only, seconds, so
  # it runs inline rather than through the farm queue, and BEFORE sync so the
  # regenerated reports are committed the same night. NIGHTLY rather than
  # weekly: the spread is the only number that decides these books' fate, and a
  # number the owner can see every morning is a number nobody can quietly
  # re-baseline later. Non-fatal by design — reporting must never block trading.
  # RETIRED 2026-08-18 with the agentic layer. report.py selects books from
  # `portfolios` WITHOUT the `active` filter, so it kept rendering the five
  # retired books as live — a running "2.0 / 26 weeks, evaluated 2027-02-01"
  # clock over frozen curves that can never diverge again. The reports in
  # data/reports/agentic/ are kept as the historical record, stamped RETIRED.
  #   was: stage agentic-report && "${PY}" agents/report.py

  # Sync is best-effort: a failure must NOT fail the nightly — the league/screen
  # results are already safe in DuckDB + data/ and will re-stage next nightly.
  stage sync
  "${PY}" engine/sync.py || echo "WARN: sync failed (exit $?) — league/screen results are safe in DuckDB + data/; will re-stage next nightly"

  # --- Farm work: LOWEST priority (§12.7 — the nightly loop preempts the farm).
  # Runs AFTER sync so data collection + the committed screen/league are already
  # safe. A failure here is logged but must NOT fail the nightly: subshell pins
  # its own exit to 0 so set -e / PIPESTATUS never see it.
  (
    set +e
    echo "--- farm (post-sync, lowest priority §12.7): mining enqueue + drain ---"
    "${PY}" engine/queue_runner.py --enqueue intraday --priority 100
    eq=$?
    # Macro / market-regime signals: daily, incremental (feeds macro_composite).
    # Sits between intraday and earnings by priority. Nothing in the fatal path
    # depends on it: the collector warns-and-continues per source, and the book
    # votes 0 on any series it cannot see.
    "${PY}" engine/queue_runner.py --enqueue signals --priority 105 \
      --params '{"mode": "incremental"}'
    es=$?
    # Earnings calendar: daily (§12.2 — feeds the earnings risk gate).
    "${PY}" engine/queue_runner.py --enqueue earnings --priority 110
    ee=$?
    # Fundamentals snapshot: weekly (§12.2) — Fridays, so the point-in-time rows
    # land on week-close data. Resumable if the drain is interrupted.
    ef=0
    if [ "$(date -u +%u)" = "5" ]; then
      "${PY}" engine/queue_runner.py --enqueue fundamentals --priority 120
      ef=$?
    fi
    "${PY}" engine/queue_runner.py --run
    rn=$?
    if [ "${eq}" -ne 0 ] || [ "${es}" -ne 0 ] || [ "${ee}" -ne 0 ] \
       || [ "${ef}" -ne 0 ] || [ "${rn}" -ne 0 ]; then
      echo "WARN: farm section had failures (intraday=${eq} signals=${es}" \
           "earnings=${ee} fundamentals=${ef} run=${rn}) — nightly NOT failed;" \
           "collect/screen/league/sync already succeeded"
    else
      echo "INFO: farm section OK (mining enqueued + queue drained)"
    fi
    exit 0
  )

  echo "=== done $(date -u +%FT%TZ) ==="
} 2>&1 | tee "${LOG}"

# Propagate failure of any piped stage and drop a breadcrumb. The stage name was
# written to STAGE_FILE from inside the (subshell) block, so it survives here.
status="${PIPESTATUS[0]}"
if [ "${status}" -ne 0 ]; then
  failed_stage="$(cat "${STAGE_FILE}" 2>/dev/null)"
  echo "TODO: run_daily failed $(date -u +%FT%TZ) (stage=${failed_stage:-unknown} exit ${status}) — inspect ${LOG}" >> "${LOG}"
  exit "${status}"
fi

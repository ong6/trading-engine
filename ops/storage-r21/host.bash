# Host helpers for the storage revision 21 deploy and rollback (sourced, never executed).
#
# Everything that touches systemd user units, the crontab or host processes lives here, so a
# rehearsal can substitute stubs (P21_HOST_HELPERS) and run deploy.sh and rollback.sh end to
# end against a store copy. Every function returns non-zero on failure; the callers run under
# `set -euo pipefail`. Requires P21_ROOT, P21_STATE and PY.

P21_MANAGED_PREFIXES='^(trading-engine-|massive-|te-autopush\.|store-sync\.|trading-data-backup\.)'
P21_TRADINGVIEW_TIMER=trading-engine-tradingview-history.timer
P21_NEW_UNITS=(trading-engine-publish-on-change.timer trading-engine-publish-on-change.service)

p21_capture() {
  # Record what ran before the deploy, once; a retry keeps the first record.
  test ! -e "$P21_STATE/host-captured" || return 0
  if crontab -l > "$P21_STATE/predeploy.crontab" 2>/dev/null; then
    touch "$P21_STATE/had-crontab"
  fi
  systemctl --user list-units --all --no-legend --plain --type=timer,service \
    | awk '{print $1" "$3}' | grep -E "$P21_MANAGED_PREFIXES" \
    > "$P21_STATE/predeploy-units" || true
  ps -eo pid,ppid,args > "$P21_STATE/predeploy-processes"
  touch "$P21_STATE/host-captured"
}

p21_pause_pullers() {
  # First, before any check: nothing may move the live checkout onto the pushed merge.
  # The nightly (crontab) pulls; te-autopush rebases unpushed commits onto origin/main.
  # A nightly already running refuses the deploy (it may pull at any moment).
  if pgrep -f 'engine/run_daily[.]sh' >/dev/null; then
    echo "a nightly is running; deploy after it ends" >&2
    return 1
  fi
  if crontab -l >/dev/null 2>&1; then crontab -r; fi
  systemctl --user stop te-autopush.timer 2>/dev/null || true
  local autopush_lock="$HOME/.local/state/te-autopush.lock"
  if test -e "$autopush_lock"; then
    flock --wait 300 "$autopush_lock" true || { echo "te-autopush still running" >&2; return 1; }
  fi
}

p21_resume_pullers() {
  # Undo p21_pause_pullers after a refusal that changed nothing else.
  if test -f "$P21_STATE/had-crontab"; then crontab "$P21_STATE/predeploy.crontab"; fi
  if grep -q '^te-autopush[.]timer active$' "$P21_STATE/predeploy-units" 2>/dev/null; then
    systemctl --user start te-autopush.timer
  fi
}

p21_quiesce() {
  # Stop the crontab and every managed timer and service (the API and UI included), then
  # prove no producer and no process holds a store file.
  if crontab -l >/dev/null 2>&1; then crontab -r; fi
  local units
  units="$(systemctl --user list-units --all --no-legend --plain --type=timer,service \
    | awk '{print $1}' | grep -E "$P21_MANAGED_PREFIXES" || true)"
  if test -n "$units"; then
    # shellcheck disable=SC2086
    systemctl --user stop $(grep '\.timer$' <<<"$units" || true) 2>/dev/null || true
    # shellcheck disable=SC2086
    systemctl --user stop $units
  fi
  local name state
  for name in $units; do
    state="$(systemctl --user show "$name" --property=ActiveState --value)"
    case "$state" in inactive|failed) ;; *) echo "still $state: $name" >&2; return 1 ;; esac
  done
  # A te-autopush run started before the stop holds its lock until it finishes.
  local autopush_lock="$HOME/.local/state/te-autopush.lock"
  if test -e "$autopush_lock"; then
    flock --wait 300 "$autopush_lock" true || { echo "te-autopush still running" >&2; return 1; }
  fi
  local stores=()
  mapfile -d '' stores < <(find "$P21_ROOT/store" -type f \
    \( -name '*.duckdb' -o -name '*.duckdb.wal' \) -print0)
  if ((${#stores[@]})) && fuser "${stores[@]}" 2>/dev/null; then
    echo "a process still holds a store file" >&2
    return 1
  fi
}

p21_autopush() {
  # The host's te-autopush, once, for local commits the data commit could not push (it
  # normalises identities and rebases only on a clean tree). A oneshot: start waits for it.
  if systemctl --user cat te-autopush.service >/dev/null 2>&1; then
    systemctl --user start te-autopush.service
  fi
}

p21_readers_ready() {
  # Start only the readers (API and UI) and wait for them to answer.
  systemctl --user restart --no-block trading-engine-api.service
  systemctl --user start --no-block trading-engine-ui.service
  local url code attempt
  for url in http://127.0.0.1:8000/health http://127.0.0.1:3000/api/health; do
    code=000
    for attempt in $(seq 1 150); do
      code="$(curl --silent --output /dev/null --write-out '%{http_code}' \
        --connect-timeout 2 --max-time 5 "$url" || true)"
      test "$code" = 200 && break
      sleep 1
    done
    test "$code" = 200 || { echo "$url answered $code" >&2; return 1; }
  done
}

p21_api_url() { printf 'http://127.0.0.1:8000'; }

p21_stage_units() {
  # Install and enable the new unit set without starting any timer (producers stay quiet).
  "$PY" -m tools.install_automation --stage > "$P21_STATE/install-stage.json"
}

p21_release() {
  # Release producers: the full install starts the repository's autostart timers and installs
  # the managed crontab (never a paused unit); host timers that were active before the
  # deploy (backup, store sync, autopush) start again, the paused TradingView timer never.
  "$PY" -m tools.install_automation --apply > "$P21_STATE/install-apply.json"
  local name state
  while read -r name state; do
    test "$state" = active && [[ "$name" == *.timer ]] || continue
    test "$name" != "$P21_TRADINGVIEW_TIMER" || continue
    systemctl --user is-active --quiet "$name" || systemctl --user start "$name"
  done < "$P21_STATE/predeploy-units"
  p21_verify_held
}

p21_schedule_check() {
  # The live schedule contract, read-only: refuse any violation outside the rules listed.
  # Before release producers are quiesced, so stopped timers (not-active) and the removed
  # crontab (missing-cron) are expected; every other rule (held-enabled, held-active,
  # not-installed, an off-manifest unit or cron line, ...) stops the deploy.
  local label="$1"; shift
  local out="$P21_STATE/schedule-contract-$label.json" rc=0
  "$PY" -m tools.schedule_contract_check --live --json --engine-root "$P21_ROOT" > "$out" || rc=$?
  test "$rc" = 0 || test "$rc" = 2 || { echo "schedule contract check failed ($rc)" >&2; return 1; }
  "$PY" - "$out" "$@" <<'PYCODE'
import json, sys
result, tolerated = json.load(open(sys.argv[1])), set(sys.argv[2:])
if result.get("errors"):
    sys.exit(f"schedule contract check errors: {result['errors']}")
refused = [v for v in result["violations"] if v["rule"] not in tolerated]
for violation in refused:
    print(f"schedule contract: {violation['rule']} {violation['subject']}", file=sys.stderr)
sys.exit(1 if refused else 0)
PYCODE
}

p21_verify_held() {
  # After release: the ops digest's checks, run now. No held or paused unit may be enabled
  # or active, and every autostart unit must be installed and enabled.
  p21_schedule_check released not-active
  if systemctl --user is-active --quiet "$P21_TRADINGVIEW_TIMER"; then
    echo "the paused TradingView timer is active" >&2
    return 1
  fi
}

p21_remove_new_units() {
  # Rollback: units the previous code does not know must not keep firing against it.
  local unit
  for unit in "${P21_NEW_UNITS[@]}"; do
    systemctl --user disable --now "$unit" 2>/dev/null || true
    rm -f "$HOME/.config/systemd/user/$unit"
  done
  systemctl --user daemon-reload
}

p21_release_previous() {
  # Rollback release: the previous code's own installer restores its unit set and crontab,
  # then every timer that was active before the deploy runs again.
  "$PY" -m tools.install_automation --apply > "$P21_STATE/rollback-install-apply.json"
  local name state
  while read -r name state; do
    test "$state" = active && [[ "$name" == *.timer ]] || continue
    systemctl --user is-active --quiet "$name" || systemctl --user start "$name"
  done < "$P21_STATE/predeploy-units"
}

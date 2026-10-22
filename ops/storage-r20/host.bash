# Host helpers for the storage revision 20 deploy and rollback (sourced, never executed).
#
# Everything that touches systemd user units, the crontab or host processes lives here, so a
# rehearsal can substitute stubs (P20_HOST_HELPERS) and run deploy.sh and rollback.sh end to
# end against a store copy. Every function returns non-zero on failure; the callers run under
# `set -euo pipefail`. Requires P20_ROOT, P20_STATE and PY.

P20_MANAGED_PREFIXES='^(trading-engine-|massive-|te-autopush\.|store-sync\.|trading-data-backup\.)'
P20_TRADINGVIEW_TIMER=trading-engine-tradingview-history.timer
P20_NEW_UNITS=(trading-engine-publish-on-change.timer trading-engine-publish-on-change.service)

p20_capture() {
  # Record what ran before the deploy, once; a retry keeps the first record.
  test ! -e "$P20_STATE/host-captured" || return 0
  if crontab -l > "$P20_STATE/predeploy.crontab" 2>/dev/null; then
    touch "$P20_STATE/had-crontab"
  fi
  systemctl --user list-units --all --no-legend --plain --type=timer,service \
    | awk '{print $1" "$3}' | grep -E "$P20_MANAGED_PREFIXES" \
    > "$P20_STATE/predeploy-units" || true
  ps -eo pid,ppid,args > "$P20_STATE/predeploy-processes"
  touch "$P20_STATE/host-captured"
}

p20_quiesce() {
  # Stop the crontab and every managed timer and service (the API and UI included), then
  # prove no producer and no process holds a store file.
  if crontab -l >/dev/null 2>&1; then crontab -r; fi
  local units
  units="$(systemctl --user list-units --all --no-legend --plain --type=timer,service \
    | awk '{print $1}' | grep -E "$P20_MANAGED_PREFIXES" || true)"
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
  local stores=()
  mapfile -d '' stores < <(find "$P20_ROOT/store" -type f \
    \( -name '*.duckdb' -o -name '*.duckdb.wal' \) -print0)
  if ((${#stores[@]})) && fuser "${stores[@]}" 2>/dev/null; then
    echo "a process still holds a store file" >&2
    return 1
  fi
}

p20_readers_ready() {
  # Start only the readers (API and UI) and wait for them to answer.
  systemctl --user start --no-block trading-engine-api.service trading-engine-ui.service
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

p20_api_url() { printf 'http://127.0.0.1:8000'; }

p20_stage_units() {
  # Install and enable the new unit set without starting any timer (producers stay quiet).
  "$PY" -m tools.install_automation --stage > "$P20_STATE/install-stage.json"
}

p20_release() {
  # Release producers: the full install starts the repository's autostart timers and installs
  # the managed crontab (never a paused unit); host timers that were active before the
  # deploy (backup, store sync, autopush) start again, the paused TradingView timer never.
  "$PY" -m tools.install_automation --apply > "$P20_STATE/install-apply.json"
  local name state
  while read -r name state; do
    test "$state" = active && [[ "$name" == *.timer ]] || continue
    test "$name" != "$P20_TRADINGVIEW_TIMER" || continue
    systemctl --user is-active --quiet "$name" || systemctl --user start "$name"
  done < "$P20_STATE/predeploy-units"
  p20_verify_held
}

p20_verify_held() {
  # The ops digest's held-active check, run now: no held or paused unit may be active.
  "$PY" -m tools.schedule_contract_check --live > "$P20_STATE/schedule-contract-live.txt"
  if systemctl --user is-active --quiet "$P20_TRADINGVIEW_TIMER"; then
    echo "the paused TradingView timer is active" >&2
    return 1
  fi
}

p20_remove_new_units() {
  # Rollback: units the previous code does not know must not keep firing against it.
  local unit
  for unit in "${P20_NEW_UNITS[@]}"; do
    systemctl --user disable --now "$unit" 2>/dev/null || true
    rm -f "$HOME/.config/systemd/user/$unit"
  done
  systemctl --user daemon-reload
}

p20_release_previous() {
  # Rollback release: the previous code's own installer restores its unit set and crontab,
  # then every timer that was active before the deploy runs again.
  "$PY" -m tools.install_automation --apply > "$P20_STATE/rollback-install-apply.json"
  local name state
  while read -r name state; do
    test "$state" = active && [[ "$name" == *.timer ]] || continue
    systemctl --user is-active --quiet "$name" || systemctl --user start "$name"
  done < "$P20_STATE/predeploy-units"
}

#!/usr/bin/env bash
# Storage revision 20 rollback (docs/revision-20-storage-deploy-checklist.md). Run from a fresh
# shell using the copy the deploy saved:   P20_STATE=<deploy state directory> bash "$P20_STATE/rollback.sh"
#
# It restores the verified pre-migration backup byte for byte and the pre-deploy commit.
# Writes to the primary made after the backup are lost (they stay in the incident copy);
# data/ follows the checkout and store/pit databases keep their rows (see the checklist).
# It refuses unless the recorded backup verifies. A rollback stopped part-way is rerun the
# same way: it keeps the first incident copy and restores the primary only once.
set -euo pipefail

: "${P20_STATE:?set P20_STATE to the deploy state directory}"
P20_STATE="$(realpath "$P20_STATE")"
test -f "$P20_STATE/state.env" || { echo "no deploy state in $P20_STATE" >&2; exit 2; }
# shellcheck disable=SC1091
source "$P20_STATE/state.env"
: "${P20_ROOT:?state.env lacks P20_ROOT}" "${P20_PREDEPLOY_SHA:?state.env lacks P20_PREDEPLOY_SHA}"
PY="${P20_PY:-$P20_ROOT/.venv/bin/python}"
export P20_ROOT P20_STATE PY
cd "$P20_ROOT"
# shellcheck disable=SC1091
source "${P20_HOST_HELPERS:-$P20_STATE/host.bash}"

trap 'rc=$?; echo "rollback stopped (exit $rc) at: $(tail -1 "$P20_STATE/rollback.log" 2>/dev/null); producers stay quiesced" >&2; exit $rc' ERR
step() { printf '== %s %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$P20_STATE/rollback.log"; }
json_field() { "$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$1" "$2"; }

step "rollback from phase ${P20_PHASE:-unknown}"
case "${P20_PHASE:-}" in
  captured|quiesced|code-switched)
    test -z "${R20_BACKUP:-}" || { echo "unexpected backup before the backup phase" >&2; false; } ;;
esac

step "quiesce producers and readers"
p20_quiesce

if test -n "${R20_BACKUP:-}"; then
  step "verify the pre-migration backup (refuses otherwise)"
  "$PY" -m tools.backup_database verify "$R20_BACKUP" > "$P20_STATE/rollback-verify.json"
  test "$(json_field "$P20_STATE/rollback-verify.json" status)" = ok
  test "$(json_field "$P20_STATE/rollback-verify.json" manifest_sha256)" = "${R20_MANIFEST:?}"

  if test ! -e "$P20_STATE/rollback-incident-kept"; then
    step "keep the incident state"
    mkdir -p -m 700 "$P20_STATE/incident"
    cp -a store/market.duckdb "$P20_STATE/incident/"
    if test -e store/market.duckdb.wal; then cp -a store/market.duckdb.wal "$P20_STATE/incident/"; fi
    if test -e store/snapshots; then mv store/snapshots "$P20_STATE/incident/quarantined-generations"; fi
    touch "$P20_STATE/rollback-incident-kept"
  fi
fi

step "remove units the previous code does not know"
p20_remove_new_units

step "check out the pre-deploy commit $P20_PREDEPLOY_SHA"
git diff --cached --exit-code >/dev/null
if test -n "$(git status --porcelain --untracked-files=no -- . ':!data' ':!logs')"; then
  echo "tracked changes outside data/ and logs/" >&2; false
fi
# Detached on purpose: the nightly pulls only on a branch with an upstream, so it cannot pull
# the rolled-back revision in again. Return to the branch once a fixed revision is approved.
git checkout --quiet --detach "$P20_PREDEPLOY_SHA"
test "$(git rev-parse HEAD)" = "$P20_PREDEPLOY_SHA"
if test "${P20_SYNC_VENV:-1}" = 1; then uv sync --extra dev --frozen --quiet; fi

if test -n "${R20_BACKUP:-}"; then
  if test ! -e "$P20_STATE/rollback-restored"; then
    step "restore the primary byte for byte"
    cp "$R20_BACKUP/market.duckdb" store/market.duckdb.restore
    cmp "$R20_BACKUP/market.duckdb" store/market.duckdb.restore
    rm -f store/market.duckdb.wal
    mv store/market.duckdb.restore store/market.duckdb
    chmod 600 store/market.duckdb
    touch "$P20_STATE/rollback-restored"
  fi
  cmp "$R20_BACKUP/market.duckdb" store/market.duckdb

  step "publish a snapshot in the previous code's format"
  "$PY" -m tools.publish_snapshot > "$P20_STATE/rollback-publish.json"
fi

step "readers"
p20_readers_ready
step "release producers with the previous unit set"
p20_release_previous
step "rolled back to $P20_PREDEPLOY_SHA"

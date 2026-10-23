#!/usr/bin/env bash
# Storage revision 20 rollback (docs/revision-20-storage-deploy-checklist.md). Run from a fresh
# shell using the copy the deploy saved:   P20_STATE=<deploy state directory> bash "$P20_STATE/rollback.sh"
#
# The live checkout stays on branch main: when HEAD carries the approved merge, the rollback
# commits `git revert -m 1 <merge>` on main, pushes it and pulls, so the nightly pull keeps
# the previous code. Nothing under data/ is copied or reverted; pending producer output goes
# through the normal data commit first. With a verified pre-migration backup recorded, the
# primary is then restored byte for byte (writes made after the backup stay in the incident
# copy), the forward records the contract migrations re-pinned are restored to the deployed
# commit's versions by a data commit, and one forward refresh must be valid before release;
# without a backup, the deploy never wrote the store, and the rollback proves the primary
# unchanged since quiesce and leaves it alone. A rollback stopped part-way is rerun the same
# way: it keeps the first incident copy, reverts once and restores the primary only once.
set -euo pipefail

: "${P20_STATE:?set P20_STATE to the deploy state directory}"
P20_STATE="$(realpath "$P20_STATE")"
test -f "$P20_STATE/state.env" || { echo "no deploy state in $P20_STATE" >&2; exit 2; }
# shellcheck disable=SC1091
source "$P20_STATE/state.env"
: "${P20_ROOT:?state.env lacks P20_ROOT}" "${P20_APPROVED_SHA:?state.env lacks P20_APPROVED_SHA}"
PY="${P20_PY:-$P20_ROOT/.venv/bin/python}"
P20_LOG=rollback.log
export P20_ROOT P20_STATE PY P20_LOG
cd "$P20_ROOT"
# shellcheck disable=SC1091
source "$P20_STATE/common.bash"
# shellcheck disable=SC1091
source "${P20_HOST_HELPERS:-$P20_STATE/host.bash}"

trap 'rc=$?; echo "rollback stopped (exit $rc) at: $(tail -1 "$P20_STATE/rollback.log" 2>/dev/null); producers stay quiesced" >&2; exit $rc' ERR

step "rollback from phase ${P20_PHASE:-unknown}"
if test -z "${R20_BACKUP:-}"; then
  case "${P20_PHASE:-}" in
    captured|quiesced|data-committed|code-switched) ;;
    *) refuse "phase ${P20_PHASE:-unknown} needs the verified backup, but none is recorded" ;;
  esac
fi

step "quiesce producers, te-autopush and readers"
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
elif test -e "$P20_STATE/store-identity.json"; then
  step "no verified backup: prove the primary unchanged since quiesce"
  p20_store_identity check
fi

step "remove units the previous code does not know"
p20_remove_new_units

step "data commit, then revert the approved merge on main"
p20_require_main
p20_data_commit storage_r20_rollback
git pull --ff-only --quiet
P20_REVERT_SHA=""
# shellcheck disable=SC1091
if test -f "$P20_STATE/rollback.env"; then source "$P20_STATE/rollback.env"; fi
if test -n "$P20_REVERT_SHA" && git merge-base --is-ancestor "$P20_REVERT_SHA" HEAD; then
  step "the approved merge is already reverted by $P20_REVERT_SHA"
elif git merge-base --is-ancestor "$P20_APPROVED_SHA" HEAD; then
  # Only data/ commits may follow the merge, so the revert restores exactly the previous code.
  p20_data_only_since "$P20_APPROVED_SHA" HEAD
  git revert -m 1 --no-edit "$P20_APPROVED_SHA" >/dev/null
  printf 'P20_REVERT_SHA=%q\n' "$(git rev-parse HEAD)" > "$P20_STATE/rollback.env"
else
  step "HEAD never carried the approved merge: no revert needed"
fi
if test -n "$(git rev-list '@{upstream}..HEAD')"; then git push --quiet origin HEAD:main; fi
git pull --ff-only --quiet
test "$(git rev-parse HEAD)" = "$(git rev-parse '@{upstream}')"
git diff --quiet "$P20_APPROVED_SHA^1" HEAD -- . ':!data' \
  || refuse "main differs from the pre-merge code outside data/"
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

  step "restore the forward records the contract migrations re-pinned"
  # E1's checkpoint and the sector and XS reports carry the re-pinned digests since the
  # deploy's contract migrations; the previous code refuses those. The versions at the
  # deployed commit (the commit the verified backup was taken at, before the migrations)
  # agree with the restored primary, which predates every post-deploy observation.
  records_from="${P20_DEPLOYED_SHA:-$P20_APPROVED_SHA^1}"
  for record in "${P20_FORWARD_RECORDS[@]}"; do
    if git cat-file -e "$records_from:$record" 2>/dev/null; then
      git show "$records_from:$record" > "$record"
    fi
  done
  p20_data_commit storage_r20_rollback_records

  step "one normal forward refresh under the previous code: E1, sector and XS must be valid"
  "$PY" -m farm.experiment_runner --report-only
  "$PY" -m engine.forward_review
  "$PY" -m engine.xs_forward_review
  for report in data/reports/forward/sector_momentum.json data/reports/forward/xs_momentum_12_1.json; do
    "$PY" -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d.get("status") != "INVALID", (sys.argv[1], d.get("status"))' "$report"
  done
  p20_data_commit storage_r20_rollback_refresh

  step "publish a snapshot in the previous code's format"
  "$PY" -m tools.publish_snapshot > "$P20_STATE/rollback-publish.json"
fi

step "readers"
p20_readers_ready
step "release producers with the previous unit set"
p20_release_previous
step "rolled back to $(git rev-parse HEAD) (code of ${P20_APPROVED_SHA:0:12}^1)"

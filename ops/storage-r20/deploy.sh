#!/usr/bin/env bash
# Storage revision 20 deploy (docs/revision-20-storage-deploy-checklist.md). Run from a fresh
# shell, never sourced, after the approved branch is merged into origin/main:
#
#   P20_ROOT=<live checkout> P20_STATE=<new private directory> \
#     P20_APPROVED_SHA=<full sha of the merge commit on origin/main> bash <copy of this file>
#
# Copy this file out of the merge first (`git show "$SHA:ops/storage-r20/deploy.sh"`): the
# checkout moves underneath it. The live checkout stays on branch main throughout and the
# deploy never copies, restores or reverts anything under data/: producer output is
# committed by the normal data commit, then main fast-forwards. Every step is checked; the
# first failure stops the deploy with producers still quiesced, and
# `$P20_STATE/rollback.sh` (copied at start) runs the rollback from another fresh shell.
# Backup, migration and publication each take the producer locks themselves.
set -euo pipefail

: "${P20_ROOT:?set P20_ROOT to the live checkout}"
: "${P20_STATE:?set P20_STATE to a new private state directory}"
: "${P20_APPROVED_SHA:?set P20_APPROVED_SHA to the full sha of the approved merge commit}"
P20_EXPECTED_PRE_CATALOG=865f64aad4529c6f2cde3d0fb72d7b70dd968b85f49905681db1aef825d59a65
P20_EXPECTED_POST_CATALOG=7286ea9b55c05d1bb16af2f2faeeb6aa69b1d5f711e1219efb2d5c27709a2e5d

[[ "$P20_APPROVED_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "P20_APPROVED_SHA must be a full sha" >&2; exit 2; }
mkdir -m 700 "$P20_STATE"          # refuses an existing directory: a retry uses rollback
P20_STATE="$(realpath "$P20_STATE")"
P20_ROOT="$(realpath "$P20_ROOT")"
cd "$P20_ROOT"
PY="${P20_PY:-$P20_ROOT/.venv/bin/python}"
export P20_ROOT P20_STATE PY
P20_RELEASING=0

on_error() {
  local rc=$?
  echo "deploy stopped (exit $rc) at: $(tail -1 "$P20_STATE/progress.log" 2>/dev/null)" >&2
  if test "$P20_RELEASING" = 1; then
    echo "producers were being released and some may be running; inspect them, then roll back with: P20_STATE=$P20_STATE bash $P20_STATE/rollback.sh" >&2
  else
    echo "producers stay quiesced; roll back with: P20_STATE=$P20_STATE bash $P20_STATE/rollback.sh" >&2
  fi
  exit "$rc"
}
trap on_error ERR

git fetch --quiet origin
git cat-file -e "$P20_APPROVED_SHA^{commit}"
for file in rollback.sh common.bash host.bash; do
  git show "$P20_APPROVED_SHA:ops/storage-r20/$file" > "$P20_STATE/$file"
done
if test -n "${P20_HOST_HELPERS:-}"; then cp "$P20_HOST_HELPERS" "$P20_STATE/host.bash"; fi
chmod 600 "$P20_STATE"/{rollback.sh,common.bash,host.bash}
# shellcheck source=ops/storage-r20/common.bash
source "$P20_STATE/common.bash"
# shellcheck source=ops/storage-r20/host.bash
source "$P20_STATE/host.bash"

step "record pre-deploy identity"
p20_require_main
git rev-parse --quiet --verify "$P20_APPROVED_SHA^2" >/dev/null \
  || refuse "the approved commit is not a merge (rollback reverts it with -m 1)"
git merge-base --is-ancestor "$P20_APPROVED_SHA" origin/main \
  || refuse "the approved merge is not on origin/main"
# Refuse before anything stops: only data/ commits may follow the approved merge on main.
p20_data_only_since "$P20_APPROVED_SHA" origin/main
record P20_ROOT "$P20_ROOT"
record P20_STATE "$P20_STATE"
record P20_PY "$PY"
record P20_PREDEPLOY_SHA "$(git rev-parse HEAD)"
record P20_APPROVED_SHA "$P20_APPROVED_SHA"
record P20_PHASE captured

step "capture units, crontab and processes"
p20_capture
step "quiesce producers, te-autopush and readers"
p20_quiesce
p20_store_identity record
record P20_PHASE quiesced

step "data commit: pending producer output is committed and pushed (engine.sync)"
# A rejected push rebases the data commit onto origin/main, which may already move the
# checkout onto the merge: the rollback decides from git, not from this phase.
p20_data_commit storage_r20_deploy
record P20_PHASE data-committed

step "fast-forward main to the approved merge"
# Checked again before the pull so a refusal leaves the checkout where it was, and after it
# because main may move in between: only data/ commits may follow the approved merge.
git fetch --quiet origin
p20_data_only_since "$P20_APPROVED_SHA" origin/main
git pull --ff-only --quiet
git merge-base --is-ancestor "$P20_APPROVED_SHA" HEAD || refuse "HEAD does not contain the approved merge"
p20_data_only_since "$P20_APPROVED_SHA" HEAD
record P20_DEPLOYED_SHA "$(git rev-parse HEAD)"
record P20_PHASE code-switched
if test "${P20_SYNC_VENV:-1}" = 1; then uv sync --extra dev --frozen --quiet; fi
test "$("$PY" -c 'import json; print(json.load(open("server/p15-registration.json"))["registration_revision"])')" = 20

step "pre-flight: the live primary is the supported pre-image (read-only)"
"$PY" -m engine.schema_migrations plan > "$P20_STATE/plan-before.json"
test "$(json_field "$P20_STATE/plan-before.json" status)" = planned
test "$(json_field "$P20_STATE/plan-before.json" expected_pre_catalog_sha256)" = "$P20_EXPECTED_PRE_CATALOG"
record P20_PRE_CATALOG "$P20_EXPECTED_PRE_CATALOG"

step "pre-flight: no NULL where the baseline tightens five deployed columns to NOT NULL (read-only)"
# The migration refuses (and rolls back) on such a NULL; stop here, before the backup, instead.
"$PY" - > "$P20_STATE/not-null-preflight.json" <<'PYCODE'
import json, sys
from engine.lib import db
checks = {
    "agent_evaluation_labels": ("round_trip_cost_bps", "net_return", "net_excess_return"),
    "daily_opportunity_execution_quality": ("post_fill_position_qty", "post_fill_cash"),
}
con = db.connect(db.DEFAULT_DB, read_only=True, wait_s=0)
try:
    counts = {
        f"{table}.{column}": con.execute(
            f'SELECT COUNT(*) FROM "{table}" WHERE "{column}" IS NULL'
        ).fetchone()[0]
        for table, columns in checks.items() for column in columns
    }
finally:
    con.close()
print(json.dumps(counts, sort_keys=True))
sys.exit(1 if any(counts.values()) else 0)
PYCODE

step "pre-migration backup"
# Backup verification refuses a path through a symlinked directory: use the canonical parent.
# The bundle is recorded only once it verifies: a rollback treats anything else as no backup.
mkdir -p -m 700 "${P20_BACKUP_PARENT:-$HOME/r20-backups}"
backup="$(realpath "${P20_BACKUP_PARENT:-$HOME/r20-backups}")/pre-migration-$(date -u +%Y%m%dT%H%M%SZ)"
"$PY" -m tools.backup_database create "$backup" --source store/market.duckdb \
  > "$P20_STATE/backup-create.json"
"$PY" -m tools.backup_database verify "$backup" > "$P20_STATE/backup-verify.json"
test "$(json_field "$P20_STATE/backup-verify.json" status)" = ok
manifest="$(json_field "$P20_STATE/backup-verify.json" manifest_sha256)"
test "$manifest" = "$(json_field "$P20_STATE/backup-create.json" manifest_sha256)"
record R20_BACKUP "$backup"
record R20_MANIFEST "$manifest"
record P20_PHASE backed-up

step "migrate"
"$PY" -m engine.schema_migrations apply "$backup" --backup-manifest-sha256 "$manifest" \
  --source-commit "$(git rev-parse HEAD)" --pre-catalog-sha256 "$P20_EXPECTED_PRE_CATALOG" \
  > "$P20_STATE/migrate.json"
"$PY" -m engine.schema_migrations plan > "$P20_STATE/plan-after.json"
test "$(json_field "$P20_STATE/plan-after.json" status)" = current
test "$(json_field "$P20_STATE/plan-after.json" expected_pre_catalog_sha256)" = "$P20_EXPECTED_POST_CATALOG"
record P20_PHASE migrated

step "runtime-contract migrations (E1, sector, XS: each accepts only the deployed digest)"
"$PY" -m farm.experiment_runner --migrate-runtime-contract
"$PY" -m engine.forward_review --migrate-runtime-contract
"$PY" -m engine.xs_forward_review --migrate-runtime-contract
# One ordinary refresh must now be valid under the re-pinned contracts.
"$PY" -m farm.experiment_runner --report-only
"$PY" -m engine.forward_review
"$PY" -m engine.xs_forward_review
"$PY" - > "$P20_STATE/contracts.json" <<'PYCODE'
import json
from engine import forward_review, xs_forward_review
from farm import experiment_runner
cfg, _ = experiment_runner.load_forward_config("e1-spy-monday", None)
checkpoint = json.loads(experiment_runner.checkpoint_path(cfg).read_text())
reports = {
    "sector": (forward_review, "data/reports/forward/sector_momentum.json"),
    "xs": (xs_forward_review, "data/reports/forward/xs_momentum_12_1.json"),
}
seen = {"e1": checkpoint["runtime_contract_sha256"]}
assert seen["e1"] == experiment_runner.EXPECTED_RUNTIME_CONTRACT_SHA256, seen
for name, (module, path) in reports.items():
    report = json.load(open(path))
    assert report.get("status") != "INVALID", (name, report.get("status"))
    seen[name] = report["frozen_runtime"]["runtime_contract_sha256"]
    assert seen[name] == module.EXPECTED_RUNTIME_CONTRACT_SHA256, (name, seen[name])
print(json.dumps(seen, sort_keys=True))
PYCODE
record P20_PHASE contracts-migrated

step "first generation"
"$PY" -m tools.publish_snapshot > "$P20_STATE/publish.json"
test "$(json_field "$P20_STATE/publish.json" status)" = published
record P20_PHASE published

step "stage units (no timer starts while producers are quiesced)"
p20_stage_units

step "readers"
p20_readers_ready
API="$(p20_api_url)"
curl --silent --fail --dump-header "$P20_STATE/health.headers" --output "$P20_STATE/health.json" "$API/health"
grep -qi '^x-data-source: snapshot' "$P20_STATE/health.headers"
grep -qi '^x-generation-id: market-' "$P20_STATE/health.headers"
curl --silent --fail --output "$P20_STATE/evaluation-status.json" "$API/agent/evaluation/status"
"$PY" -c 'import json,sys; g=json.load(open(sys.argv[1]))["generation"]; assert g["pending_publication"] is False, g' \
  "$P20_STATE/evaluation-status.json"
curl --silent --fail --output "$P20_STATE/meta.json" "$API/meta"
# The readers' own projection of the three frozen experiments: none may be INVALID.
"$PY" -c '
import json, sys
meta = json.load(open(sys.argv[1]))
states = {key: (meta.get(key) or {}).get("status") for key in ("e1_forward", "forward_review", "xs_forward_review")}
print(states)
assert all(state not in (None, "INVALID") for state in states.values()), states' "$P20_STATE/meta.json"
"$PY" -m tools.check_invariants --snapshot latest --engine-root "$P20_ROOT" \
  > "$P20_STATE/invariants.txt"
"$PY" -m tools.publish_snapshot --retention-dry-run > "$P20_STATE/retention.json"
record P20_PHASE readers-verified

step "live schedule contract before release (quiesced: only stopped timers and the removed crontab)"
p20_schedule_check before-release not-active missing-cron

step "release producers"
P20_RELEASING=1
record P20_PHASE releasing
p20_release
record P20_PHASE released
step "deployed $(git rev-parse HEAD); rollback after this point loses writes made since release"

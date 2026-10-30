#!/usr/bin/env bash
# Storage revision 21 deploy (docs/revision-21-storage-deploy-checklist.md). Run from a fresh
# shell, never sourced, after the approved branch is merged into origin/main:
#
#   P21_ROOT=<live checkout> P21_STATE=<new private directory> \
#     P21_APPROVED_SHA=<full sha of the merge commit on origin/main> bash <copy of this file>
#
# Copy this file out of the merge first (`git show "$SHA:ops/storage-r21/deploy.sh"`): the
# checkout moves underneath it. The live checkout stays on branch main throughout and the
# deploy never copies, restores or reverts anything under data/: producer output is
# committed by the normal data commit, then main fast-forwards. Every step is checked; the
# first failure stops the deploy with producers still quiesced, and
# `$P21_STATE/rollback.sh` (copied at start) runs the rollback from another fresh shell.
# Backup, migration and publication each take the producer locks themselves.
set -euo pipefail

: "${P21_ROOT:?set P21_ROOT to the live checkout}"
: "${P21_STATE:?set P21_STATE to a new private state directory}"
: "${P21_APPROVED_SHA:?set P21_APPROVED_SHA to the full sha of the approved merge commit}"
P21_EXPECTED_PRE_CATALOG=865f64aad4529c6f2cde3d0fb72d7b70dd968b85f49905681db1aef825d59a65
P21_EXPECTED_POST_CATALOG=7286ea9b55c05d1bb16af2f2faeeb6aa69b1d5f711e1219efb2d5c27709a2e5d

[[ "$P21_APPROVED_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "P21_APPROVED_SHA must be a full sha" >&2; exit 2; }
mkdir -m 700 "$P21_STATE"          # refuses an existing directory: a retry uses rollback
P21_STATE="$(realpath "$P21_STATE")"
P21_ROOT="$(realpath "$P21_ROOT")"
cd "$P21_ROOT"
PY="${P21_PY:-$P21_ROOT/.venv/bin/python}"
export P21_ROOT P21_STATE PY
P21_RELEASING=0

P21_PAUSED_ONLY=0
on_error() {
  local rc=$?
  echo "deploy stopped (exit $rc) at: $(tail -1 "$P21_STATE/progress.log" 2>/dev/null)" >&2
  if test "$P21_PAUSED_ONLY" = 1; then
    # Refused before anything but the pause: undo it, nothing else changed.
    trap - ERR
    p21_resume_pullers && echo "refused before quiescing; the nightly crontab and te-autopush are resumed" >&2
    exit "$rc"
  fi
  if test "$P21_RELEASING" = 1; then
    echo "producers were being released and some may be running; inspect them, then roll back with: P21_STATE=$P21_STATE bash $P21_STATE/rollback.sh" >&2
  else
    echo "producers stay quiesced; roll back with: P21_STATE=$P21_STATE bash $P21_STATE/rollback.sh" >&2
  fi
  exit "$rc"
}
trap on_error ERR

git fetch --quiet origin
git cat-file -e "$P21_APPROVED_SHA^{commit}"
for file in rollback.sh common.bash host.bash; do
  git show "$P21_APPROVED_SHA:ops/storage-r21/$file" > "$P21_STATE/$file"
done
if test -n "${P21_HOST_HELPERS:-}"; then cp "$P21_HOST_HELPERS" "$P21_STATE/host.bash"; fi
chmod 600 "$P21_STATE"/{rollback.sh,common.bash,host.bash}
# shellcheck source=ops/storage-r21/common.bash
source "$P21_STATE/common.bash"
# shellcheck source=ops/storage-r21/host.bash
source "$P21_STATE/host.bash"

step "pause the nightly and te-autopush (nothing may pull the merge before quiescence)"
p21_capture
P21_PAUSED_ONLY=1
p21_pause_pullers

step "record pre-deploy identity"
p21_require_main
git rev-parse --quiet --verify "$P21_APPROVED_SHA^2" >/dev/null \
  || refuse "the approved commit is not a merge (rollback reverts it with -m 1)"
git merge-base --is-ancestor "$P21_APPROVED_SHA" origin/main \
  || refuse "the approved merge is not on origin/main"
# Refuse before anything else stops: only data/ commits may follow the approved merge on main.
p21_data_only_since "$P21_APPROVED_SHA" origin/main
record P21_ROOT "$P21_ROOT"
record P21_STATE "$P21_STATE"
record P21_PY "$PY"
record P21_PREDEPLOY_SHA "$(git rev-parse HEAD)"
record P21_APPROVED_SHA "$P21_APPROVED_SHA"
record P21_PHASE captured

step "quiesce producers, te-autopush and readers"
P21_PAUSED_ONLY=0
p21_quiesce
p21_store_identity record
record P21_PHASE quiesced

step "data commit: pending producer output is committed and pushed (engine.sync)"
# A rejected push rebases the data commit onto origin/main, which may already move the
# checkout onto the merge: the rollback decides from git, not from this phase.
p21_data_commit storage_r21_deploy
record P21_PHASE data-committed

step "fast-forward main to the approved merge"
# Checked again before the pull so a refusal leaves the checkout where it was, and after it
# because main may move in between: only data/ commits may follow the approved merge.
git fetch --quiet origin
p21_data_only_since "$P21_APPROVED_SHA" origin/main
git pull --ff-only --quiet
git merge-base --is-ancestor "$P21_APPROVED_SHA" HEAD || refuse "HEAD does not contain the approved merge"
p21_data_only_since "$P21_APPROVED_SHA" HEAD
record P21_DEPLOYED_SHA "$(git rev-parse HEAD)"
record P21_PHASE code-switched
if test "${P21_SYNC_VENV:-1}" = 1; then uv sync --extra dev --frozen --quiet; fi
test "$("$PY" -c 'import json; print(json.load(open("server/p15-registration.json"))["registration_revision"])')" = 21

step "pre-flight: the live primary is the supported pre-image (read-only)"
"$PY" -m engine.schema_migrations plan > "$P21_STATE/plan-before.json"
test "$(json_field "$P21_STATE/plan-before.json" status)" = planned
test "$(json_field "$P21_STATE/plan-before.json" expected_pre_catalog_sha256)" = "$P21_EXPECTED_PRE_CATALOG"
record P21_PRE_CATALOG "$P21_EXPECTED_PRE_CATALOG"

step "pre-flight: no NULL where the baseline tightens five deployed columns to NOT NULL (read-only)"
# The migration refuses (and rolls back) on such a NULL; stop here, before the backup, instead.
"$PY" - > "$P21_STATE/not-null-preflight.json" <<'PYCODE'
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
mkdir -p -m 700 "${P21_BACKUP_PARENT:-$HOME/r21-backups}"
backup="$(realpath "${P21_BACKUP_PARENT:-$HOME/r21-backups}")/pre-migration-$(date -u +%Y%m%dT%H%M%SZ)"
"$PY" -m tools.backup_database create "$backup" --source store/market.duckdb \
  > "$P21_STATE/backup-create.json"
"$PY" -m tools.backup_database verify "$backup" > "$P21_STATE/backup-verify.json"
test "$(json_field "$P21_STATE/backup-verify.json" status)" = ok
manifest="$(json_field "$P21_STATE/backup-verify.json" manifest_sha256)"
test "$manifest" = "$(json_field "$P21_STATE/backup-create.json" manifest_sha256)"
record R21_BACKUP "$backup"
record R21_MANIFEST "$manifest"
record P21_PHASE backed-up

step "migrate"
"$PY" -m engine.schema_migrations apply "$backup" --backup-manifest-sha256 "$manifest" \
  --source-commit "$(git rev-parse HEAD)" --pre-catalog-sha256 "$P21_EXPECTED_PRE_CATALOG" \
  > "$P21_STATE/migrate.json"
"$PY" -m engine.schema_migrations plan > "$P21_STATE/plan-after.json"
test "$(json_field "$P21_STATE/plan-after.json" status)" = current
test "$(json_field "$P21_STATE/plan-after.json" expected_pre_catalog_sha256)" = "$P21_EXPECTED_POST_CATALOG"
record P21_PHASE migrated

step "runtime-contract migrations (E1, sector, XS: each accepts only the deployed digest)"
"$PY" -m farm.experiment_runner --migrate-runtime-contract
"$PY" -m engine.forward_review --migrate-runtime-contract
"$PY" -m engine.xs_forward_review --migrate-runtime-contract
# One ordinary refresh must now be valid under the re-pinned contracts.
"$PY" -m farm.experiment_runner --report-only
"$PY" -m engine.forward_review
"$PY" -m engine.xs_forward_review
"$PY" - > "$P21_STATE/contracts.json" <<'PYCODE'
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
record P21_PHASE contracts-migrated

step "first generation"
"$PY" -m tools.publish_snapshot > "$P21_STATE/publish.json"
test "$(json_field "$P21_STATE/publish.json" status)" = published
record P21_PHASE published

step "stage units (no timer starts while producers are quiesced)"
p21_stage_units

step "readers"
p21_readers_ready
API="$(p21_api_url)"
curl --silent --fail --dump-header "$P21_STATE/health.headers" --output "$P21_STATE/health.json" "$API/health"
grep -qi '^x-data-source: snapshot' "$P21_STATE/health.headers"
grep -qi '^x-generation-id: market-' "$P21_STATE/health.headers"
curl --silent --fail --output "$P21_STATE/evaluation-status.json" "$API/agent/evaluation/status"
"$PY" -c 'import json,sys; g=json.load(open(sys.argv[1]))["generation"]; assert g["pending_publication"] is False, g' \
  "$P21_STATE/evaluation-status.json"
curl --silent --fail --output "$P21_STATE/meta.json" "$API/meta"
# The readers' own projection of the three frozen experiments: none may be INVALID.
"$PY" -c '
import json, sys
meta = json.load(open(sys.argv[1]))
states = {key: (meta.get(key) or {}).get("status") for key in ("e1_forward", "forward_review", "xs_forward_review")}
print(states)
assert all(state not in (None, "INVALID") for state in states.values()), states' "$P21_STATE/meta.json"
"$PY" -m tools.check_invariants --snapshot latest --engine-root "$P21_ROOT" \
  > "$P21_STATE/invariants.txt"
"$PY" -m tools.publish_snapshot --retention-dry-run > "$P21_STATE/retention.json"
record P21_PHASE readers-verified

step "live schedule contract before release (quiesced: only stopped timers and the removed crontab)"
p21_schedule_check before-release not-active missing-cron

step "release producers"
P21_RELEASING=1
record P21_PHASE releasing
p21_release
record P21_PHASE released
step "deployed $(git rev-parse HEAD); rollback after this point loses writes made since release"

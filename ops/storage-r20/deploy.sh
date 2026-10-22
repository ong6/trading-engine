#!/usr/bin/env bash
# Storage revision 20 deploy (docs/revision-20-storage-deploy-checklist.md). Run from a fresh
# shell, never sourced:
#
#   P20_ROOT=<live checkout> P20_STATE=<new private directory> P20_APPROVED_SHA=<full sha> \
#     bash <copy of this file>
#
# Copy this file out of the approved commit first (`git show "$SHA:ops/storage-r20/deploy.sh"`):
# the checkout switches commits underneath it. Every step is checked; the first failure
# stops the deploy with producers still quiesced, and `$P20_STATE/rollback.sh` (copied here
# at start) runs the rollback from another fresh shell. Backup, migration and publication
# each take the producer locks themselves; this script never holds them.
set -euo pipefail

: "${P20_ROOT:?set P20_ROOT to the live checkout}"
: "${P20_STATE:?set P20_STATE to a new private state directory}"
: "${P20_APPROVED_SHA:?set P20_APPROVED_SHA to the full approved commit}"
P20_EXPECTED_PRE_CATALOG=865f64aad4529c6f2cde3d0fb72d7b70dd968b85f49905681db1aef825d59a65
P20_EXPECTED_POST_CATALOG=7286ea9b55c05d1bb16af2f2faeeb6aa69b1d5f711e1219efb2d5c27709a2e5d

[[ "$P20_APPROVED_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "P20_APPROVED_SHA must be a full sha" >&2; exit 2; }
mkdir -m 700 "$P20_STATE"          # refuses an existing directory: a retry uses rollback
P20_STATE="$(realpath "$P20_STATE")"
P20_ROOT="$(realpath "$P20_ROOT")"
cd "$P20_ROOT"
PY="${P20_PY:-$P20_ROOT/.venv/bin/python}"
export P20_ROOT P20_STATE PY

trap 'rc=$?; echo "deploy stopped (exit $rc) at: $(tail -1 "$P20_STATE/progress.log" 2>/dev/null)"; echo "producers stay quiesced; roll back with: P20_STATE=$P20_STATE bash $P20_STATE/rollback.sh" >&2; exit $rc' ERR

step() { printf '== %s %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$P20_STATE/progress.log"; }
record() { printf '%s=%q\n' "$1" "$2" >> "$P20_STATE/state.env"; }
json_field() { "$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$1" "$2"; }

step "record pre-deploy identity (before any pull)"
if git remote get-url origin >/dev/null 2>&1; then git fetch --quiet origin; fi
git cat-file -e "$P20_APPROVED_SHA^{commit}"
record P20_ROOT "$P20_ROOT"
record P20_STATE "$P20_STATE"
record P20_PY "$PY"
record P20_PREDEPLOY_SHA "$(git rev-parse HEAD)"
record P20_PREDEPLOY_BRANCH "$(git symbolic-ref --quiet --short HEAD || true)"
record P20_APPROVED_SHA "$P20_APPROVED_SHA"
git show "$P20_APPROVED_SHA:ops/storage-r20/rollback.sh" > "$P20_STATE/rollback.sh"
if test -n "${P20_HOST_HELPERS:-}"; then
  cp "$P20_HOST_HELPERS" "$P20_STATE/host.bash"
else
  git show "$P20_APPROVED_SHA:ops/storage-r20/host.bash" > "$P20_STATE/host.bash"
fi
chmod 600 "$P20_STATE/rollback.sh" "$P20_STATE/host.bash"
# shellcheck source=ops/storage-r20/host.bash
source "$P20_STATE/host.bash"
record P20_PHASE captured

step "capture units, crontab and processes"
p20_capture
step "quiesce producers and readers"
p20_quiesce
record P20_PHASE quiesced

step "check out the approved commit"
git diff --cached --exit-code >/dev/null
if test -n "$(git status --porcelain --untracked-files=no -- . ':!data' ':!logs')"; then
  echo "tracked changes outside data/ and logs/" >&2; false
fi
# Generated data/ and logs/ changes are kept aside, the tracked paths restored so the
# checkout can move, and the kept files put back afterwards (the runbook's P22 pattern).
mkdir -m 700 "$P20_STATE/predeploy-artifacts"
git diff --name-only -z -- data logs | while IFS= read -r -d '' changed; do
  mkdir -p "$P20_STATE/predeploy-artifacts/$(dirname "$changed")"
  cp -a "$changed" "$P20_STATE/predeploy-artifacts/$changed"
done
git checkout --quiet HEAD -- data logs 2>/dev/null || git checkout --quiet HEAD -- data
if git symbolic-ref --quiet HEAD >/dev/null; then
  git merge --ff-only --quiet "$P20_APPROVED_SHA"
else
  git checkout --quiet --detach "$P20_APPROVED_SHA"
fi
test "$(git rev-parse HEAD)" = "$P20_APPROVED_SHA"
cp -a "$P20_STATE/predeploy-artifacts/." .
if test "${P20_SYNC_VENV:-1}" = 1; then uv sync --extra dev --frozen --quiet; fi
test "$("$PY" -c 'import json; print(json.load(open("server/p15-registration.json"))["registration_revision"])')" = 20
record P20_PHASE code-switched

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
mkdir -p -m 700 "${P20_BACKUP_PARENT:-$HOME/r20-backups}"
R20_BACKUP="$(realpath "${P20_BACKUP_PARENT:-$HOME/r20-backups}")/pre-migration-$(date -u +%Y%m%dT%H%M%SZ)"
record R20_BACKUP "$R20_BACKUP"
"$PY" -m tools.backup_database create "$R20_BACKUP" --source store/market.duckdb \
  > "$P20_STATE/backup-create.json"
"$PY" -m tools.backup_database verify "$R20_BACKUP" > "$P20_STATE/backup-verify.json"
test "$(json_field "$P20_STATE/backup-verify.json" status)" = ok
R20_MANIFEST="$(json_field "$P20_STATE/backup-verify.json" manifest_sha256)"
test "$R20_MANIFEST" = "$(json_field "$P20_STATE/backup-create.json" manifest_sha256)"
record R20_MANIFEST "$R20_MANIFEST"
record P20_PHASE backed-up

step "migrate"
"$PY" -m engine.schema_migrations apply "$R20_BACKUP" --backup-manifest-sha256 "$R20_MANIFEST" \
  --source-commit "$P20_APPROVED_SHA" --pre-catalog-sha256 "$P20_EXPECTED_PRE_CATALOG" \
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
for report in data/reports/forward/sector_momentum.json data/reports/forward/xs_momentum_12_1.json; do
  "$PY" -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d.get("status") != "INVALID", (sys.argv[1], d.get("status"))' "$report"
done
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
"$PY" -m tools.check_invariants --snapshot latest --engine-root "$P20_ROOT" \
  > "$P20_STATE/invariants.txt"
"$PY" -m tools.publish_snapshot --retention-dry-run > "$P20_STATE/retention.json"
record P20_PHASE readers-verified

step "release producers"
p20_release
record P20_PHASE released
step "deployed $P20_APPROVED_SHA; rollback after this point loses writes made since release"

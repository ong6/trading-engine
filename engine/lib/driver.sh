#!/usr/bin/env bash
# Shared preamble for every engine/run_*.sh driver (architecture review
# 2026-09-02 §A2: the same 25 lines were copied into each driver). Sourced, not
# executed. A driver is now:
#
#   set -euo pipefail
#   DRIVER_NAME=run_daily            # header/breadcrumb label
#   DRIVER_LOCK=.nightly.lock        # per-driver overlap-guard file (repo root)
#   DRIVER_LOCK_MSG="another run_daily is still running (lock held) — aborting this nightly"
#   DRIVER_LOG_PREFIX=run            # logs/<prefix>-YYYY-MM-DD.log
#   DRIVER_LOG_APPEND=0              # 1 -> tee -a (default), 0 -> tee (truncate)
#   DRIVER_STAGE_FILE=logs/.last_stage   # optional: enables stage() + "stage=" in the breadcrumb
#   source "$(dirname "${BASH_SOURCE[0]}")/lib/driver.sh"
#   body() { stage foo; "${PY}" -m engine.foo; ... }
#   driver_main body
#
# Sourcing performs, in this order and exactly as the drivers used to inline:
#   1. REPO_ROOT resolved from THIS file's location (engine/lib -> repo), cd there.
#   2. Overlap guard: non-blocking flock on fd 9 over ${REPO_ROOT}/${DRIVER_LOCK};
#      held -> print DRIVER_LOCK_MSG, exit 1.
#   3. PY=<repo>/.venv/bin/python, PYTHONUNBUFFERED=1 (keeps the tee'd log and
#      cron.log live), mkdir -p logs, LOG=logs/<prefix>-$(date +%F).log.
#   4. Stage breadcrumb state file (when DRIVER_STAGE_FILE is set): the tee'd
#      block is a pipeline and runs in a SUBSHELL, so a stage name set inside
#      it would not survive to the failure breadcrumb; stage() writes it to a
#      small file the breadcrumb reads back.
#
# driver_main runs the body inside the tee'd block and propagates failure.
#
# errexit + pipefail interplay (fixed 2026-09-02): with `set -e` armed in the
# driver's shell, a failing `{ … } | tee` pipeline exits the script right there,
# before `status="${PIPESTATUS[0]}"` ever runs — the breadcrumb was dead code
# (4 Tracebacks in logs/cron.log, 0 "TODO: run_daily failed" lines). So errexit
# is suspended in the parent around the pipeline ONLY, and re-armed as the first
# statement inside the block: the block is a subshell that inherits `set +e`,
# and a stage failure must still abort the remaining stages. Do NOT rewrite this
# as `… | tee && status=0 || status=$?` — bash ignores errexit for every command
# inside a compound command that sits on the left of `&&`/`||`, so a failed
# collect would silently run on into screen/league (proven with a harness).

: "${DRIVER_NAME:?driver.sh: set DRIVER_NAME before sourcing}"
: "${DRIVER_LOCK:?driver.sh: set DRIVER_LOCK before sourcing}"
: "${DRIVER_LOG_PREFIX:?driver.sh: set DRIVER_LOG_PREFIX before sourcing}"
DRIVER_LOCK_MSG="${DRIVER_LOCK_MSG:-another ${DRIVER_NAME} is still running (lock held) — aborting}"
DRIVER_LOG_APPEND="${DRIVER_LOG_APPEND:-1}"
DRIVER_STAGE_FILE="${DRIVER_STAGE_FILE:-}"

# Resolve repo root from this file's location (path-independent).
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

# Overlap guard: refuse to start if a prior run of this driver is still alive.
# Non-blocking flock on fd 9 covers the whole script body.
exec 9>"${REPO_ROOT}/${DRIVER_LOCK}"
if ! flock -n 9; then
  echo "ERROR: ${DRIVER_LOCK_MSG}"
  exit 1
fi

PY="${REPO_ROOT}/.venv/bin/python"
export PYTHONUNBUFFERED=1
mkdir -p "${REPO_ROOT}/logs"
LOG="${REPO_ROOT}/logs/${DRIVER_LOG_PREFIX}-$(date +%F).log"

if [ -n "${DRIVER_STAGE_FILE}" ]; then
  STAGE_FILE="${REPO_ROOT}/${DRIVER_STAGE_FILE}"
  stage() { echo "$1" > "${STAGE_FILE}"; }
  : > "${STAGE_FILE}"
else
  stage() { :; }
fi

# driver_main <body-function>: tee the body into ${LOG}, then propagate the
# first failing stage's exit code with a TODO breadcrumb (read PIPESTATUS
# BEFORE re-arming errexit, which is itself a command).
driver_main() {
  local body="$1" status failed_stage
  set +e
  if [ "${DRIVER_LOG_APPEND}" = "1" ]; then
    {
      set -e
      echo "=== ${DRIVER_NAME} $(date -u +%FT%TZ) ==="
      "${body}"
      echo "=== done $(date -u +%FT%TZ) ==="
    } 2>&1 | tee -a "${LOG}"
  else
    {
      set -e
      echo "=== ${DRIVER_NAME} $(date -u +%FT%TZ) ==="
      "${body}"
      echo "=== done $(date -u +%FT%TZ) ==="
    } 2>&1 | tee "${LOG}"
  fi
  status="${PIPESTATUS[0]}"
  set -e
  if [ "${status}" -ne 0 ]; then
    if [ -n "${DRIVER_STAGE_FILE}" ]; then
      failed_stage="$(cat "${STAGE_FILE}" 2>/dev/null)"
      echo "TODO: ${DRIVER_NAME} failed $(date -u +%FT%TZ) (stage=${failed_stage:-unknown} exit ${status}) — inspect ${LOG}" | tee -a "${LOG}"
    else
      echo "TODO: ${DRIVER_NAME} failed $(date -u +%FT%TZ) (exit ${status}) — inspect ${LOG}" | tee -a "${LOG}"
    fi
    exit "${status}"
  fi
}

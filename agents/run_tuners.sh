#!/usr/bin/env bash
# Weekly parameter-tuning sessions for the three tuner books
# (agentic-strategies-design books 2, 3 and 4). Same proven harness as the news
# analyst and the daily gaters: zero-tool `claude -p` on the subscription login,
# wrapper does all I/O, validator is the only thing that may change a config.
#
# Cron: 30 10 * * 0 — Sunday 10:30 UTC, AFTER the 06:00 UTC walk-forward grid
# (~3h) has landed, so each session reads a FRESH out-of-sample re-validation
# rather than last week's.
#
# FAIL-SOFT, ALWAYS. Every path logs a breadcrumb and exits 0. A dead session, a
# locked store, an out-of-bounds proposal — all of them mean the book keeps
# running on its currently applied parameters, which is a completely safe state.
#
# The 06:00 walk-forward drain can still hold the DuckDB writer lock at 10:30,
# so the validator's write gets a long lock budget (single-writer store).

set -uo pipefail

export HOME="${HOME:-~}"
export PATH="${HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin"
# 30 minutes of bounded retry on a locked store before the validator gives up
# and logs the proposal as rejected-for-infrastructure (engine/lib/db.py).
export TRADING_ENGINE_LOCK_WAIT_S="${TRADING_ENGINE_LOCK_WAIT_S:-1800}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}" || exit 0

PY="${REPO_ROOT}/.venv/bin/python"
CLAUDE="${HOME}/.local/bin/claude"
LOG="${REPO_ROOT}/logs/agentic-tuner.log"
RUN_DATE="${TUNER_DATE:-$(date -u +%F)}"
AGENTS_DIR="${TRADING_ENGINE_AGENTS_DIR:-${REPO_ROOT}/agents}"
BOOKS="${TUNER_BOOKS:-adaptive_mr agentic_alloc stop_tuner_turtle}"
DB_ARG="${TUNER_DB:-}"

mkdir -p "${REPO_ROOT}/logs" "${REPO_ROOT}/scratch"
log() { echo "$(date -u +%FT%TZ) $*" >> "${LOG}"; }

exec 9>"${REPO_ROOT}/.agentic-tuner.lock"
if ! flock -n 9; then
  log "SKIP: another tuner run holds the lock"
  exit 0
fi

log "=== tuner run start (${RUN_DATE}) books='${BOOKS}' ==="

WORK="$(mktemp -d "${REPO_ROOT}/scratch/tuner.XXXXXX")" || {
  log "TODO: could not create work dir — skipping this run"; exit 0; }
# shellcheck disable=SC2064
trap "rm -rf '${WORK}'" EXIT

jread() {  # jq is absent on this box; the venv python always exists
  if command -v jq >/dev/null 2>&1; then jq -r "$2" < "$1"
  else "${PY}" -c "import json,sys; d=json.load(open(sys.argv[1])); sys.stdout.write(str($3))" "$1"; fi
}

NO_TOOLS='{"permissions":{"deny":["Bash","Edit","Write","Read","Agent","WebFetch","WebSearch","Skill","NotebookEdit","Glob","Grep","Task","TodoWrite"]}}'

for BOOK in ${BOOKS}; do
  log "--- ${BOOK} ---"
  PROMPT="${WORK}/${BOOK}.prompt.txt"
  META="${WORK}/${BOOK}.meta.json"
  OUT_JSON="${WORK}/${BOOK}.out.json"

  if ! "${PY}" "${SCRIPT_DIR}/tuner_prep.py" --book "${BOOK}" \
        --prompt-out "${PROMPT}" --meta-out "${META}" --date "${RUN_DATE}" \
        --agents-dir "${AGENTS_DIR}" ${DB_ARG:+--db "${DB_ARG}"} >>"${LOG}" 2>&1; then
    log "TODO: ${BOOK} prep failed — no proposal, book keeps its current parameters"
    continue
  fi

  BOOK_EXISTS="$(jread "${META}" '.book_exists' 'd["book_exists"]')"
  if [ "${BOOK_EXISTS}" != "True" ] && [ "${BOOK_EXISTS}" != "true" ]; then
    log "OK: ${BOOK} is not in the store yet — nothing to tune"
    continue
  fi
  log "INFO: ${BOOK} v$(jread "${META}" '.version' 'd["version"]')" \
      "prompt=$(wc -c < "${PROMPT}") bytes"

  if ! timeout 900 "${CLAUDE}" -p "$(cat "${PROMPT}")" \
        --permission-mode dontAsk \
        --strict-mcp-config \
        --settings "${NO_TOOLS}" \
        --max-turns 1 \
        --output-format json > "${OUT_JSON}" 2>>"${LOG}"; then
    log "TODO: ${BOOK} claude -p exited non-zero (quota / auth / network?) —" \
        "no proposal, book keeps its current parameters. Inspect ${LOG}."
    continue
  fi

  IS_ERROR="$(jread "${OUT_JSON}" '.is_error' 'd.get("is_error", False)' 2>>"${LOG}")"
  if [ "${IS_ERROR}" = "true" ] || [ "${IS_ERROR}" = "True" ]; then
    log "TODO: ${BOOK} claude reported is_error=true" \
        "($(jread "${OUT_JSON}" '.result' 'str(d.get("result",""))[:200]')) — no proposal"
    continue
  fi

  PROPOSAL="${AGENTS_DIR}/${BOOK}/proposals/${RUN_DATE}.json"
  mkdir -p "$(dirname "${PROPOSAL}")"
  if ! "${PY}" - "${OUT_JSON}" "${PROPOSAL}" <<'PYEOF' >>"${LOG}" 2>&1; then
import json, re, sys
raw = json.load(open(sys.argv[1])).get("result", "") or ""
m = re.search(r"\{.*\}", raw, re.S)
if not m:
    print(f"[tuner] no JSON object in the model response (first 200 chars): {raw[:200]!r}")
    raise SystemExit(1)
json.dump(json.loads(m.group(0)), open(sys.argv[2], "w"), indent=2)
PYEOF
    log "TODO: ${BOOK} could not parse a JSON proposal out of the response — no change"
    continue
  fi

  # The proposal file is kept on disk permanently (agents/<book>/proposals/)
  # whether or not it is applied: the 26-week review reads what the agent ASKED
  # for, not only what it got.
  # shellcheck disable=SC2086
  "${PY}" "${SCRIPT_DIR}/validator.py" --book "${BOOK}" \
      --proposal "${PROPOSAL}" --date "${RUN_DATE}" \
      --agents-dir "${AGENTS_DIR}" --session "tuner-${RUN_DATE}" \
      ${DB_ARG:+--db "${DB_ARG}"} >>"${LOG}" 2>&1 \
    || log "WARN: ${BOOK} validator exited non-zero — book keeps its current parameters"
done

# Refresh the agentic reports so the Sunday review reads this cycle's outcome.
# shellcheck disable=SC2086
"${PY}" "${SCRIPT_DIR}/report.py" ${DB_ARG:+--db "${DB_ARG}"} \
    --agents-dir "${AGENTS_DIR}" >>"${LOG}" 2>&1 \
  || log "WARN: agentic report refresh failed — reports are stale, nothing else affected"

log "=== tuner run done (${RUN_DATE}) ==="
exit 0

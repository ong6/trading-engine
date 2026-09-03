#!/usr/bin/env bash
# News analyst — pre-market brief over the RSS headlines collected since the last
# successful run. Implements trading/trading-engine/news-analyst-design.md:
# a zero-tool, wrapper-assembled `claude -p` call. THIS script gathers every input
# and writes every output; the model call is a pure text -> text transform with no
# tools, no permission surface and no filesystem access to reason about.
#
# NEWS IS NON-CRITICAL. Every failure path logs a breadcrumb and exits 0 — a broken
# news run must never look like a broken nightly, and must never page the owner. The
# state file only advances on success, so a failed run's headlines are re-covered by
# the next one.
#
# Cron: 0 11 * * 1-5  (~7am ET pre-market / 7pm SGT), clear of the 22:30 UTC nightly.

set -uo pipefail

# cron gives a near-empty environment; the Claude CLI needs HOME to find its
# subscription OAuth credentials (~/.claude/.credentials.json).
export HOME="${HOME:-$(getent passwd "$(id -u)" | cut -d: -f6)}"
export PATH="${HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}" || exit 0

PY="${REPO_ROOT}/.venv/bin/python"
CLAUDE="${HOME}/.local/bin/claude"
LOG_DIR="${REPO_ROOT}/logs"
REPORT_DIR="${REPO_ROOT}/data/reports/news"
STATE_FILE="${REPO_ROOT}/data/news_analyst_state.json"
LOG="${LOG_DIR}/news-analyst.log"
RUN_DATE="$(date -u +%F)"

mkdir -p "${LOG_DIR}" "${REPORT_DIR}" "${REPO_ROOT}/scratch"

log() { echo "$(date -u +%FT%TZ) $*" >> "${LOG}"; }

# Overlap guard (same pattern as engine/run_daily.sh). A held lock means a prior
# run is still in the model call — skip rather than double-spend the quota.
exec 9>"${REPO_ROOT}/.news-analyst.lock"
if ! flock -n 9; then
  log "SKIP: another news_analyst run holds the lock"
  exit 0
fi

log "=== news_analyst start (${RUN_DATE}) ==="

WORK="$(mktemp -d "${REPO_ROOT}/scratch/news-analyst.XXXXXX")" || {
  log "TODO: could not create work dir — skipping this run"; exit 0; }
# shellcheck disable=SC2064
trap "rm -rf '${WORK}'" EXIT

PROMPT="${WORK}/prompt.txt"
META="${WORK}/meta.json"
OUT_JSON="${WORK}/out.json"

# --- 1. Gather every input into one prompt file -----------------------------
if ! "${PY}" -m engine.news_analyst_prep \
      --state "${STATE_FILE}" --prompt-out "${PROMPT}" --meta-out "${META}" \
      --date "${RUN_DATE}" >>"${LOG}" 2>&1; then
  log "TODO: prep step failed — no brief written, state NOT advanced (next run re-covers)"
  exit 0
fi

# jq is not installed on this box; the venv python is always present, so JSON is
# read with python. Kept as a preference order in case jq shows up later.
jread() {  # jread <file> <jq-filter> <python-expression over `d`>
  if command -v jq >/dev/null 2>&1; then
    jq -r "$2" < "$1"
  else
    "${PY}" -c "import json,sys; d=json.load(open(sys.argv[1])); sys.stdout.write(str($3))" "$1"
  fi
}

NEW_COUNT="$(jread "${META}" '.new_count' 'd["new_count"]')"
# Treat anything non-numeric as zero: a garbled meta must degrade to "skip the
# model call", never to an arithmetic error that silently falls through.
case "${NEW_COUNT}" in ''|*[!0-9]*) log "WARN: unreadable new_count '${NEW_COUNT}' — treating as 0"; NEW_COUNT=0 ;; esac

# --- 2. No new headlines → skip the model call entirely ---------------------
if [ "${NEW_COUNT}" -eq 0 ]; then
  log "OK: 0 new headlines since last successful run — no claude call, no brief"
  exit 0
fi

POSITIONS_OK="$(jread "${META}" '.positions_ok' 'd["positions_ok"]')"
log "INFO: ${NEW_COUNT} new headlines; positions_ok=${POSITIONS_OK}; prompt $(wc -c < "${PROMPT}") bytes"

# --- 3. The model call: zero tools, one turn, subscription auth --------------
#
# NOT `--bare`, despite the design note. Verified 2026-08-04: `--bare` reads
# "strictly ANTHROPIC_API_KEY or apiKeyHelper ... OAuth and keychain are never
# read", so every --bare call returns is_error with "Not logged in · Please run
# /login". The design's whole billing premise is the subscription OAuth login, so
# --bare is simply incompatible with it. The properties --bare was chosen for are
# reproduced explicitly instead:
#   --settings '{"permissions":{"deny":[...]}}'  removes the tools outright
#                                                (verified: "no Bash tool is
#                                                available in this session")
#   --strict-mcp-config                          no MCP servers load
#   --permission-mode dontAsk                    never blocks on a prompt
#   --max-turns 1                                one turn, bounded
# `timeout` is the last line of defence: cron must never inherit a wedged call.
NO_TOOLS='{"permissions":{"deny":["Bash","Edit","Write","Read","Agent","WebFetch","WebSearch","Skill","NotebookEdit","Glob","Grep","Task","TodoWrite"]}}'
if ! timeout 900 "${CLAUDE}" -p "$(cat "${PROMPT}")" \
      --permission-mode dontAsk \
      --strict-mcp-config \
      --settings "${NO_TOOLS}" \
      --max-turns 1 \
      --output-format json > "${OUT_JSON}" 2>>"${LOG}"; then
  log "TODO: claude -p exited non-zero (quota window exhausted / auth / network?) —" \
      "no brief written for ${RUN_DATE}, state NOT advanced so these ${NEW_COUNT}" \
      "headlines are re-covered next run. Inspect ${LOG}."
  exit 0
fi

# The CLI can also report failure in-band (is_error=true with the message sitting
# in .result), so an exit code of 0 is not on its own proof of a usable brief.
IS_ERROR="$(jread "${OUT_JSON}" '.is_error' 'd.get("is_error", False)' 2>>"${LOG}")"
if [ "${IS_ERROR}" = "true" ] || [ "${IS_ERROR}" = "True" ]; then
  log "TODO: claude reported is_error=true ($(jread "${OUT_JSON}" '.result' 'str(d.get("result",""))[:200]')) —" \
      "no brief written, state NOT advanced"
  exit 0
fi

BRIEF="${WORK}/brief.md"
if ! jread "${OUT_JSON}" '.result' 'd.get("result","")' > "${BRIEF}" 2>>"${LOG}"; then
  log "TODO: could not parse .result out of the claude response — state NOT advanced"
  exit 0
fi

if [ ! -s "${BRIEF}" ]; then
  log "TODO: claude returned an empty result — state NOT advanced"
  exit 0
fi

# --- 4. Write the outputs ----------------------------------------------------
{
  echo "<!-- generated by engine/news_analyst.sh on $(date -u +%FT%TZ);"
  echo "     ${NEW_COUNT} headlines, titles only, no article bodies -->"
  echo
  cat "${BRIEF}"
} > "${REPORT_DIR}/${RUN_DATE}.md"
cp "${REPORT_DIR}/${RUN_DATE}.md" "${REPORT_DIR}/latest.md"

# --- 5. Advance the watermark — ONLY now that a brief exists on disk ----------
"${PY}" - "${META}" "${STATE_FILE}" "${RUN_DATE}" <<'PYEOF' >>"${LOG}" 2>&1
import json, sys
meta = json.load(open(sys.argv[1]))
json.dump({
    "last_scraped_at": meta["last_scraped_at"],
    "last_guid": meta["last_guid"],
    "last_success_date": sys.argv[3],
    "last_new_count": meta["new_count"],
}, open(sys.argv[2], "w"), indent=2)
open(sys.argv[2], "a").write("\n")
PYEOF

log "OK: wrote ${REPORT_DIR}/${RUN_DATE}.md (+ latest.md), state advanced to $(jread "${META}" '.last_scraped_at' 'd["last_scraped_at"]')"
exit 0

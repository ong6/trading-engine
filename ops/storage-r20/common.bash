# Shared by deploy.sh and rollback.sh (sourced from the deploy state directory, never
# executed). Requires P20_ROOT, P20_STATE and PY; the callers run under `set -euo pipefail`
# from the live checkout.

step() { printf '== %s %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$P20_STATE/${P20_LOG:-progress.log}"; }
record() { printf '%s=%q\n' "$1" "$2" >> "$P20_STATE/state.env"; }
refuse() { echo "refused: $*" >&2; return 1; }
json_field() { "$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$1" "$2"; }

p20_require_main() {
  # The live checkout stays on branch main with an upstream; nothing half-done in git.
  test "$(git symbolic-ref --quiet --short HEAD || true)" = main || refuse "HEAD is not branch main"
  git rev-parse --quiet --verify '@{upstream}' >/dev/null || refuse "main has no upstream"
  local marker
  for marker in rebase-merge rebase-apply MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD; do
    test ! -e "$(git rev-parse --git-path "$marker")" || refuse "a git $marker is in progress" || return 1
  done
  git diff --cached --quiet || refuse "the index holds staged changes"
}

p20_data_only_since() {
  # Every commit in base..tip is an ordinary (non-merge) commit that changes only data/.
  local base="$1" tip="${2:-HEAD}" commit
  test -z "$(git rev-list --merges "$base..$tip")" || refuse "$tip adds merge commits after $base"
  for commit in $(git rev-list "$base..$tip"); do
    if git diff-tree --no-commit-id --name-only -r "$commit" | grep -qv '^data/'; then
      refuse "commit $commit after $base changes files outside data/" || return 1
    fi
  done
}

p20_data_commit() {
  # The normal data commit: engine.sync commits pending producer output under data/ and
  # pushes it; te-autopush pushes any local commit sync left behind. Afterwards the tracked
  # tree is clean and origin/main holds every local commit.
  "$PY" -m engine.sync --driver "$1"
  git fetch --quiet origin
  if test -n "$(git rev-list '@{upstream}..HEAD')"; then
    p20_autopush
    git fetch --quiet origin
  fi
  test -z "$(git status --porcelain --untracked-files=no)" \
    || refuse "tracked changes remain after the data commit: $(git status --porcelain --untracked-files=no | head -5)"
  test -z "$(git rev-list '@{upstream}..HEAD')" || refuse "local commits are not on origin/main"
}

p20_store_identity() {
  # record: save the primary's (and WAL's) file identity; check: refuse if it changed.
  "$PY" - "$P20_ROOT/store/market.duckdb" "$P20_STATE/store-identity.json" "$1" <<'PYCODE'
import json, os, sys
path, saved, mode = sys.argv[1:]
def identity(name):
    try:
        st = os.stat(name)
    except FileNotFoundError:
        return None
    return [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns]
current = {"primary": identity(path), "wal": identity(path + ".wal")}
if mode == "record":
    with open(saved, "x") as handle:
        json.dump(current, handle)
elif json.load(open(saved)) != current:
    sys.exit("the primary changed since quiesce but no verified backup is recorded")
PYCODE
}

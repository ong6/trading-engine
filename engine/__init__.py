"""trading-engine data layer + nightly driver.

`engine/` is a real package: import `engine.lib.db`, `engine.collect`, ... and run
entry points as `python -m engine.collect` from the repo root (every shell driver
does `cd "${REPO_ROOT}"` first). The old `sys.path.insert` + `from lib import db`
idiom is gone (refactor step 1, 2026-09-03).
"""

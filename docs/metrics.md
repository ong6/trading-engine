# Drift metrics

`python -m tools.metrics_snapshot` writes one dated JSON to `data/reports/metrics/` and
regenerates the table in [`data/reports/metrics/README.md`](../data/reports/metrics/README.md).
It reads committed artifacts and Git only, so it runs on any clone with no database and no
network. Every agent session ends by publishing a snapshot with `--check-budget`.

The point is to make drift visible in numbers an agent cannot argue with. A session that
grew `server/` by 5,000 lines while the research counters did not move is a bad session,
however green the tests are.

## What is measured

| Group | Metric | Why it matters | Healthy direction |
|---|---|---|---|
| Code size | LOC per layer: `engine`, `sim`, `farm` (product), `server`, `tools`, `tests`, `ui/app` | Growth in `server`/`tools` with flat product is governance for its own sake | Flat or down for frozen layers |
| Code size | `docs_md`, `buildlog` line counts | Doc mass is read cost for every future session | Flat or down |
| Commit shape | Non-screen commits in the last 30 days; how many touched research paths, how many touched product, how many were support-only | Support-only share is the ceremony ratio | Support-only share falling |
| Commit shape | Largest single commit (insertions) | Unreviewable drops are how 61k lines landed in one day | Under 1,500 |
| Ledger | Mean and max lines of the last ten BUILDLOG entries; SHA-256 mentions | Entry length and hash spam measure narration over decision | Under 25 lines, at most one hash |
| Ledger | Count and max size of format-v2 entries | Confirms the new format is being used | All new entries v2 |
| Research | Sector momentum shared sessions (of 200), E1 observations (of 40), XS status, active book count, league staleness | The only counters that represent progress toward the mission | Sessions and observations rising; books falling to ~10 (P2) |
| Budget | Pass/fail against `scope-budget.json` | Hard stop for frozen layers | `ok` |

## Baseline, 2026-09-18

| Metric | Value |
|---|---|
| `server` LOC | 45,769 |
| `tools` LOC | 6,828 (includes this tool) |
| Product LOC (`engine`+`sim`+`farm`) | 28,180 |
| `tests` LOC | 55,712 |
| Non-screen commits, 30 days | 41, of which 12 support-only |
| Largest commit, 30 days | 86,905 insertions |
| BUILDLOG last ten entries | mean 741 lines, 913 SHA-256 mentions |
| Sector momentum | 9 / 200 sessions, ACCUMULATING |
| E1 | 8 / 40 observations |
| Active books | 21 |

## Reading a snapshot

- **Frozen layer up, research flat** → the session built something the scope ledger forbids.
  Revert or get a plan approved.
- **Budget OVER** → the test suite is red until the owner raises the ceiling in
  `feedback.md`. Do not edit `scope-budget.json` in the same change that needs it.
- **Research counters unchanged for a week** → check the scheduler, not the strategy.
- **Books count down** → P2 is running; expected.

## Not measured on purpose

Test count, coverage, and "gates passing" are not tracked. They were the numbers the previous
loop optimised, and they went up while nothing useful happened.

# Owner feedback ledger

Dated verdicts from the owner about the repo or agent behaviour, each with the rule it
changed. The newest entry overrides any older document, including `AGENTS.md`. Agents read
this second, and append here (never rewrite) when the owner gives a verdict in conversation.

Format: date, the verdict in the owner's terms, the rule change, where it was applied.

## 2026-09-18 — Review of progress; move to maintain mode

**Verdict.** Rated 6/10 overall: engineering rigor 8, research honesty 9, research output 3,
scope control 3, process health 4. The loop had drifted from "find an edge" to "build
governance for an edge that doesn't exist." `server/` at 46k lines is larger than the whole
product and almost all of it serves a broker that has no authority. Yesterday's single commit
added 161 files and 61k lines against a standing order for small reviewable commits. BUILDLOG
entries average 741 lines and repeat four hashes each. Owner asked for the docs, skills,
metrics and feedback layers to be hardened so long-running LLM sessions stop doing work "we
don't need yet", then for follow-up plans.

**Rule changes.**

1. Mode is MAINTAIN. Default session outcome is verify, report, stop. → `AGENTS.md`.
2. Every change must pass the admission test (backlog row, approved plan, or reproduced
   defect). → `AGENTS.md`.
3. `server/`, `tools/`, and the research runtime are frozen at ceilings in
   `docs/scope-budget.json`; the test suite fails on growth. → `tests/test_operating_contract.py`.
4. BUILDLOG entries: at most 25 lines, one hash. → `AGENTS.md`, budget, test.
5. No new documentation-pinning tests. → `AGENTS.md`, `docs/scope.md`.
6. `docs/live-readiness-goal.md` is reference, not the work queue; workstreams C, D, E are
   frozen pending the P4 decision. → banner in that file, `docs/scope.md`.
7. A drift metrics snapshot closes every session. → `tools/metrics_snapshot.py`,
   `docs/metrics.md`.
8. Owner verdicts are written here and applied in the same session. → `AGENTS.md`.

**Plans opened.** P1 appliance mode, P2 league collapse, P3 point-in-time data, P4 broker
decision. All `proposed`; owner promotes.

**Ceiling changes.** None yet. Record any raise here with the reason before editing the
budget file.

## 2026-09-18 — Repo made public; history scrubbed, dates untouched

**Verdict.** Owner asked to publish the repo as a showcase for quant and trading-firm readers and
to link it from junxiong.dev. Owner also suggested spreading commit dates across a year; declined,
because the artifacts are all dated from 2026-07-15 and a false timeline would be both dishonest
and trivially detectable. The real record (first commit 2026-07-16, nightly since 2026-07-17)
stands.

**What changed.** History rewritten with `git filter-repo` to replace an employer email, a devbox
home path, an internal tool name and an agent co-author trailer; every commit date and count is
unchanged (201 commits). Working tree scrubbed the same way in `` before the rewrite.
Visibility set to public. Any existing clone must be re-cloned.

**Rule changes.**

1. Public repo: no employer, devbox or internal-tool identifiers in any file or commit message.
   "One Linux box" is the only description of the host. → `AGENTS.md` absolute rules.
2. Commit dates are never edited. → this ledger.

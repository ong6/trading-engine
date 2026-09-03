# agentic_alloc — vs frozen twin `agentic_alloc_frozen`

> **RETIRED 2026-08-18.** The agentic layer was switched off and this book is
> `active = FALSE`. The numbers below are frozen at 2026-08-17 and will not
> change again; any "n / 26 weeks" clock or spread-vs-twin figure is a historical
> artefact, not a live result. See BUILDLOG 2026-08-18.

_role **tuner** (weekly sleeve weights) · param version **v1** · 0 applied / 0 rejected change(s) · 1 lesson(s) · generated 2026-08-18 09:22 UTC._

Charter: `agents/agentic_alloc/charter.md` (frozen — bounds, objective and kill criterion are not re-registrable mid-stream).

## Spread vs the frozen twin

Common window **2026-08-04 → 2026-08-17** (10 session(s)); both curves rebased to 1.0000 at 2026-08-04. AI inception 2026-08-03, twin inception 2026-08-03 — identical, so the common window is the whole life of both books.

* AI return over the window: **+0.96%**
* Twin return over the window: **+0.96%**
* **Spread (AI − twin): +0.00%**
* Max drawdown over the same window — AI −0.08%, twin −0.08%
* Elapsed: **2.0 / 26 weeks**, evaluated 2027-02-01

### Last 10 session(s)

| Session | agentic_alloc equity | idx | agentic_alloc_frozen equity | idx | Cumulative spread |
|---|---|---|---|---|---|
| 2026-08-04 | $39,000 | 1.0000 | $39,000 | 1.0000 | **+0.00%** |
| 2026-08-05 | $39,000 | 1.0000 | $39,000 | 1.0000 | **+0.00%** |
| 2026-08-06 | $39,000 | 1.0000 | $39,000 | 1.0000 | **+0.00%** |
| 2026-08-07 | $39,000 | 1.0000 | $39,000 | 1.0000 | **+0.00%** |
| 2026-08-10 | $39,149 | 1.0038 | $39,149 | 1.0038 | **+0.00%** |
| 2026-08-11 | $39,199 | 1.0051 | $39,199 | 1.0051 | **+0.00%** |
| 2026-08-12 | $39,302 | 1.0077 | $39,302 | 1.0077 | **+0.00%** |
| 2026-08-13 | $39,384 | 1.0098 | $39,384 | 1.0098 | **+0.00%** |
| 2026-08-14 | $39,405 | 1.0104 | $39,405 | 1.0104 | **+0.00%** |
| 2026-08-17 | $39,373 | 1.0096 | $39,373 | 1.0096 | **+0.00%** |

## Change log

_No `changes.jsonl` yet — the agent has made no recorded proposal for this book._

## Gating

_Not applicable — this is a **tuner** book. It adjusts parameters on a weekly cadence and never vetoes or downscales an individual entry, so there is no veto ledger and no hit rate to compute._

## Disclosures — read before any number below

1. **The spread is the ONLY measure.** Each AI book is scored against its frozen
   twin and against nothing else — not SPY, not the league table, not its own
   absolute return. The twin runs the same algo with never-adjusted parameters,
   so the difference is the closest thing to a clean read on whether the agent's
   bounded adjustments added anything. An AI book that is up while its twin is
   up more has **lost**.
2. **Different inceptions are rebased, never subtracted raw.** `momo_stopped`,
   `turtle_breakout` and `pead_ear` are pre-existing live books with an earlier
   inception than the AI books that shadow them. Every spread below is computed
   on the **common overlapping window only**: both equity curves are rebased to
   1.0 at the first session on which both books have a `sim_equity` row, and the
   spread runs from there. The common-window start is printed on every row. No
   number on this page compares total returns measured from different days.
3. **The window is short and the sample is tiny.** Weeks elapsed are printed
   against the 26-week horizon. At this length the spread is dominated by a
   handful of fills; it is a diagnostic, not a result. Nothing here is
   statistically significant and nothing here should be read as though it were.
4. **Paper fills.** Every number is simulated — t+1-open fills with the league's
   slippage and liquidity guards. No agent has ever moved real money, and the
   fill assumptions flatter both sides of the spread roughly equally.
5. **No mid-stream re-registration.** The charter (bounds, objective, kill
   criterion) is frozen at book creation. If a charter is edited, the book's
   record restarts — it is not spliced onto the old one. The change log below is
   append-only and rejected proposals are shown, not hidden: a loop that
   proposes badly and self-rejects is a different animal from one that never
   proposes.
6. **The 26-week kill criterion applies to the AGENT LOOP, not the algo book.**
   If the spread is not positive at the evaluation date, what gets switched off
   is the agent's authority to adjust — the underlying algorithmic book keeps
   trading as its own frozen twin. Killing the loop is a cheap, reversible,
   pre-registered act; it is not a verdict on the strategy.
7. **A veto's counterfactual is only observable through the twin.** The AI book
   never took the vetoed name, so its outcome is unknowable from the AI book's
   own fills. The only honest counterfactual is what the TWIN did on the same
   signal, and it exists only where the twin actually bought the name. Vetoes
   the twin also skipped are reported and excluded from the hit rate — there is
   no counterfactual to score.



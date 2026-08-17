# adaptive_mr — vs frozen twin `adaptive_mr_frozen`

_role **tuner** (weekly mean-reversion params) · param version **v1** · 0 applied / 0 rejected change(s) · 1 lesson(s) · generated 2026-08-17 22:34 UTC._

Charter: `agents/adaptive_mr/charter.md` (frozen — bounds, objective and kill criterion are not re-registrable mid-stream).

## Spread vs the frozen twin

Common window **2026-08-04 → 2026-08-17** (10 session(s)); both curves rebased to 1.0000 at 2026-08-04. AI inception 2026-08-03, twin inception 2026-08-03 — identical, so the common window is the whole life of both books.

* AI return over the window: **+3.66%**
* Twin return over the window: **+3.66%**
* **Spread (AI − twin): +0.00%**
* Max drawdown over the same window — AI −1.06%, twin −1.06%
* Elapsed: **2.0 / 26 weeks**, evaluated 2027-02-01

### Last 10 session(s)

| Session | adaptive_mr equity | idx | adaptive_mr_frozen equity | idx | Cumulative spread |
|---|---|---|---|---|---|
| 2026-08-04 | $39,000 | 1.0000 | $39,000 | 1.0000 | **+0.00%** |
| 2026-08-05 | $39,166 | 1.0042 | $39,166 | 1.0042 | **+0.00%** |
| 2026-08-06 | $39,116 | 1.0030 | $39,116 | 1.0030 | **+0.00%** |
| 2026-08-07 | $39,105 | 1.0027 | $39,105 | 1.0027 | **+0.00%** |
| 2026-08-10 | $39,113 | 1.0029 | $39,113 | 1.0029 | **+0.00%** |
| 2026-08-11 | $38,750 | 0.9936 | $38,750 | 0.9936 | **+0.00%** |
| 2026-08-12 | $38,900 | 0.9974 | $38,900 | 0.9974 | **+0.00%** |
| 2026-08-13 | $38,868 | 0.9966 | $38,868 | 0.9966 | **+0.00%** |
| 2026-08-14 | $40,514 | 1.0388 | $40,514 | 1.0388 | **+0.00%** |
| 2026-08-17 | $40,426 | 1.0366 | $40,426 | 1.0366 | **+0.00%** |

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



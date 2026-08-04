# stop_tuner_turtle — vs frozen twin `turtle_breakout`

_role **tuner** (weekly stop / breakout params) · param version **v1** · 0 applied / 0 rejected change(s) · 1 lesson(s) · generated 2026-08-04 09:54 UTC._

Charter: `agents/stop_tuner_turtle/charter.md` (frozen — bounds, objective and kill criterion are not re-registrable mid-stream).

> **No data yet — no `sim_equity` rows yet: stop_tuner_turtle.** Nothing below is measurable until both this book and `turtle_breakout` have `sim_equity` rows on a shared session.

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



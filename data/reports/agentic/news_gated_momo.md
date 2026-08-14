# news_gated_momo — vs frozen twin `momo_stopped`

_role **gater** (vetoes / downscales entries on news) · param version **v1** · 0 applied / 0 rejected change(s) · 1 lesson(s) · generated 2026-08-14 22:35 UTC._

Charter: `agents/news_gated_momo/charter.md` (frozen — bounds, objective and kill criterion are not re-registrable mid-stream).

## Spread vs the frozen twin

Common window **2026-08-04 → 2026-08-14** (9 session(s)); both curves rebased to 1.0000 at 2026-08-04. AI inception 2026-08-03, twin inception 2026-07-28 — **different**, which is exactly why the raw total returns of these two books are never subtracted from each other here.

* AI return over the window: **+5.70%**
* Twin return over the window: **+5.95%**
* **Spread (AI − twin): −0.24%**
* Max drawdown over the same window — AI −1.76%, twin −2.28%
* Elapsed: **1.6 / 26 weeks**, evaluated 2027-02-01

### Last 9 session(s)

| Session | news_gated_momo equity | idx | momo_stopped equity | idx | Cumulative spread |
|---|---|---|---|---|---|
| 2026-08-04 | $39,000 | 1.0000 | $40,097 | 1.0000 | **+0.00%** |
| 2026-08-05 | $39,000 | 1.0000 | $39,778 | 0.9920 | **+0.80%** |
| 2026-08-06 | $39,000 | 1.0000 | $39,957 | 0.9965 | **+0.35%** |
| 2026-08-07 | $39,000 | 1.0000 | $40,501 | 1.0101 | **−1.01%** |
| 2026-08-10 | $38,845 | 0.9960 | $40,243 | 1.0036 | **−0.76%** |
| 2026-08-11 | $38,315 | 0.9824 | $39,579 | 0.9871 | **−0.46%** |
| 2026-08-12 | $39,529 | 1.0136 | $40,698 | 1.0150 | **−0.14%** |
| 2026-08-13 | $40,318 | 1.0338 | $41,607 | 1.0376 | **−0.39%** |
| 2026-08-14 | $41,224 | 1.0570 | $42,482 | 1.0595 | **−0.24%** |

## Change log

_No `changes.jsonl` yet — the agent has made no recorded proposal for this book._

## Veto ledger and hit rate

_No `gate-<date>.json` decision file exists yet — this book has made no recorded gating call, so there is nothing to score._

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



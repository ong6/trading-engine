# earnings_context_pead — vs frozen twin `pead_ear`

_role **gater** (vetoes / downscales entries on earnings context) · param version **v1** · 1 applied / 0 rejected change(s) · 1 lesson(s) · generated 2026-08-11 22:34 UTC._

Charter: `agents/earnings_context_pead/charter.md` (frozen — bounds, objective and kill criterion are not re-registrable mid-stream).

## Spread vs the frozen twin

Common window **2026-08-04 → 2026-08-11** (6 session(s)); both curves rebased to 1.0000 at 2026-08-04. AI inception 2026-08-03, twin inception 2026-07-28 — **different**, which is exactly why the raw total returns of these two books are never subtracted from each other here.

* AI return over the window: **−1.31%**
* Twin return over the window: **−1.08%**
* **Spread (AI − twin): −0.23%**
* Max drawdown over the same window — AI −2.40%, twin −1.32%
* Elapsed: **1.1 / 26 weeks**, evaluated 2027-02-01

### Last 6 session(s)

| Session | earnings_context_pead equity | idx | pead_ear equity | idx | Cumulative spread |
|---|---|---|---|---|---|
| 2026-08-04 | $39,000 | 1.0000 | $38,854 | 1.0000 | **+0.00%** |
| 2026-08-05 | $38,246 | 0.9807 | $38,803 | 0.9987 | **−1.80%** |
| 2026-08-06 | $38,062 | 0.9760 | $38,447 | 0.9895 | **−1.36%** |
| 2026-08-07 | $38,493 | 0.9870 | $38,614 | 0.9938 | **−0.68%** |
| 2026-08-10 | $38,482 | 0.9867 | $38,340 | 0.9868 | **−0.01%** |
| 2026-08-11 | $38,488 | 0.9869 | $38,435 | 0.9892 | **−0.23%** |

## Change log

_1 proposal(s) from `changes.jsonl` (1 applied, 0 rejected). Append-only: rejected proposals are shown, not hidden._

| Date | Status | Version | Diff | Rationale | Evidence | Reject reason |
|---|---|---|---|---|---|---|
| 2026-08-04 | **applied** | vNone | `gate` →0 veto / 0 downscale | None of the 8 preview candidates (ATKR, NWL, LIND, LIFE, NPK, TWST, WT, SNAP) appear anywhere in today's brief, which covers watchlist names (CBOE, VIRT, FTNT, etc.) and macro only. No adverse news, no vetoes, no downscales — all 8 recorded as class unclear per D-A5b and taken at full size. | · | · |

## Veto ledger and hit rate

_1 gate file(s) · 0 veto(es) · 0 downscale(s) · 10 entry(ies) the book took on the same sessions._

**How a veto is scored.** A veto's counterfactual is only observable through the twin: the AI book never bought the name, so the only evidence of what the veto cost or saved is whether the FROZEN TWIN bought it on the next session, and what happened to it afterwards. Where the twin bought, the name's +5-session return is measured from the twin's fill price, and the veto counts as **correct** when that return is negative. Where the twin also skipped the name there is no counterfactual and the veto is excluded from the hit rate — it is not scored as a win. **A downscale is never counted in the hit rate**: it changes position size, not selection, so it cannot be right or wrong about a name. Names whose +5-session bar does not exist yet are shown as `pending` and are never extrapolated.

| Measure | Value |
|---|---|
| Vetoes issued | 0 |
| …that the twin actually bought (scoreable) | 0 |
| …with no twin entry (no counterfactual, excluded) | 0 |
| …resolved (+5 bar exists) | 0 |
| …pending | 0 |
| Vetoes correct (subsequent return negative) | 0 |
| **Veto hit rate** | **·** |
| Mean +5d return, vetoed-and-twin-bought | · |
| Median +5d return, vetoed-and-twin-bought | · |
| Entries taken (resolved / pending) | 0 / 10 |
| Mean +5d return, taken | · |
| Median +5d return, taken | · |
| **Difference (vetoed − taken)** | **·** |

A gater that is selecting well shows a **negative** difference: the names it refused did worse than the names it let through. A positive difference means the gate is vetoing the wrong names.

### Veto ledger

| Gate date | Bites on | Ticker | Twin bought? | Twin fill | +5d | Verdict | Reason |
|---|---|---|---|---|---|---|---|

### Entries taken on gated sessions (+5d)

| Session | Ticker | Fill | +5d |
|---|---|---|---|
| 2026-08-05 | AMRC | $27.72 | `pending` |
| 2026-08-05 | BLZE | $19.83 | `pending` |
| 2026-08-05 | IBTA | $37.68 | `pending` |
| 2026-08-05 | INSP | $63.41 | `pending` |
| 2026-08-05 | ORIC | $13.66 | `pending` |
| 2026-08-05 | PAY | $43.19 | `pending` |
| 2026-08-05 | PLTR | $162.21 | `pending` |
| 2026-08-05 | UFPT | $328.98 | `pending` |
| 2026-08-05 | W | $115.00 | `pending` |
| 2026-08-05 | ZBRA | $369.01 | `pending` |

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



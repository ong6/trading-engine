# Agentic books — AI vs frozen twin

_5 paired book(s) · 5 of 5 AI book(s) exist in `portfolios` · generated 2026-08-07 22:33 UTC._

Each row is one AI book and the frozen twin it is measured against. The twin runs the SAME algorithm with never-adjusted parameters; the AI book runs that algorithm plus an agent whose authority is bounded by a frozen charter. **The spread between them is the whole experiment** — everything else on this page is context.

Spreads are computed on the common overlapping window only, because three of the twins are pre-existing books with an earlier inception than the AI books shadowing them. Both curves are rebased to 1.0 at the first session both books have an equity row for, and the window start is stated on every row.

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


## Scoreboard

| AI book | Frozen twin | Role | Common window from | AI ret | Twin ret | **Spread** | AI max DD | Twin max DD | Param v | Applied | Rejected | Veto hit rate | Weeks | Evaluation |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [news_gated_momo](news_gated_momo.md) | `momo_stopped` | gater | 2026-08-04 (4 sess) | +0.00% | +1.01% | **−1.01%** | +0.00% | −0.80% | v1 | 0 | 0 | · | 0.6/26 | 2027-02-01 |
| [adaptive_mr](adaptive_mr.md) | `adaptive_mr_frozen` | tuner | 2026-08-04 (4 sess) | +0.27% | +0.27% | **+0.00%** | −0.15% | −0.15% | v1 | 0 | 0 | — | 0.6/26 | 2027-02-01 |
| [agentic_alloc](agentic_alloc.md) | `agentic_alloc_frozen` | tuner | 2026-08-04 (4 sess) | +0.00% | +0.00% | **+0.00%** | +0.00% | +0.00% | v1 | 0 | 0 | — | 0.6/26 | 2027-02-01 |
| [stop_tuner_turtle](stop_tuner_turtle.md) | `turtle_breakout` | tuner | 2026-08-04 (4 sess) | −0.28% | −0.50% | **+0.23%** | −0.94% | −1.49% | v1 | 0 | 0 | — | 0.6/26 | 2027-02-01 |
| [earnings_context_pead](earnings_context_pead.md) | `pead_ear` | gater | 2026-08-04 (4 sess) | −1.30% | −0.62% | **−0.68%** | −2.40% | −1.05% | v1 | 1 | 0 | · | 0.6/26 | 2027-02-01 |

_`Param v` is `portfolios.config → agent_version` (1 when the key is absent). `Applied`/`Rejected` count rows in `changes.jsonl`. `Weeks` counts from the AI book's own inception to the last shared session, against the 26-week horizon; the loop is evaluated 2027-02-01._

## Kill criterion (pre-registered)

At **2027-02-01**, after 26 weeks, an AI book whose spread against its frozen twin is not positive loses its agent loop: the agent's authority to adjust is withdrawn and the book continues as the pure algorithm. The algorithmic book is NOT killed by this criterion — only the loop is. Nothing about the criterion, the bounds or the twin may be re-registered mid-stream; a changed charter starts a new record.


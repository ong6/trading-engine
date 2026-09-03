# Charter — `news_gated_momo` (AI book 1 of 5)

**FROZEN 2026-08-04.** This file is the agent's constitution. It is registered
before any evidence exists and is not edited afterwards — not to widen a bound,
not to change the cadence, not to re-pick the twin. Amending it means killing
this book and registering a new one with a new id and a new 26-week clock.

## Objective

Run `momo_stopped`'s algorithm unchanged (weekly top-10 banded RS selection, the
daily 15%-below-weekly-reference stop) and remove from each day's *proposed
entries* the names an adverse binary news event is about to hit — announced
acquisitions of the buyer's balance sheet, guidance cuts, regulatory action,
accounting or fraud allegations, going-concern language.

The agent is not here to pick stocks. It is here to answer one question per
candidate: **is there a headline that makes this specific entry a bad idea
today?** If it cannot answer yes with a cited headline, the entry stands.

## Permissions — asymmetric, enforced in code

| Allowed | Forbidden |
|---|---|
| `veto` a proposed BUY | adding any name the algo did not propose |
| `downscale` a proposed BUY (scale 0.25–1.00) | raising any size |
| — | touching a SELL, a stop, or an exit |
| — | changing any numeric strategy parameter |

Enforcement is `sim/strategies/base.py::apply_agent_gate` plus
`agents/validator.py`, not trust. The gate reads only
`agents/news_gated_momo/gate-<date>.json`; anything else in the model's output is
discarded. **No gate file for a date → pure algo (fail-open).**

## Adjustable "parameters" and their hard bounds

No strategy parameter is adjustable in this book — the algo is byte-identical to
the twin's. What is bounded is the *gate itself*:

| Knob | Bound | Why this bound |
|---|---|---|
| `action` | `veto` or `downscale` only | the asymmetry is the whole safety argument |
| `scale` | 0.25 – 1.00 | below 0.25 a "downscale" is a veto in disguise; the two are accounted separately |
| `max_decisions` | 20 per day | the book proposes at most ~10 entries a week; 20 is generous headroom and still bounds a runaway session |
| `max_veto_share_of_candidates` | 0.50 | an agent that vetoes most of the book is no longer a gate, it is a market-timing overlay it has no mandate for. Half is the line |
| `reason_min_chars` | 20 | a veto without a stated reason is not reviewable, and every veto is reviewed at 26 weeks |

<!-- BOUNDS -->
```json
{
  "book": "news_gated_momo",
  "twin": "momo_stopped",
  "kind": "gater",
  "cadence": "daily",
  "gate": {
    "allowed_actions": ["veto", "downscale"],
    "min_scale": 0.25,
    "max_scale": 1.0,
    "max_decisions": 20,
    "max_veto_share_of_candidates": 0.5,
    "reason_min_chars": 20
  },
  "params": {}
}
```

## Cadence

* **Daily gate session** — 21:40 UTC, weekdays, ~50 minutes ahead of the 22:30
  UTC nightly. It must run before `sim/league.py`'s `generate_all`, because
  orders generated at 22:30 fill at the *next* open; a veto arriving after that
  is a veto of a trade already made.
* **Weekly lessons** — appended by the Sunday tuner cycle from the veto
  hit-rate: of the names this book vetoed, what did the twin's fill in the same
  name do over the following 5 sessions?

## Evidence the wrapper hands the session (nothing else; the model has zero tools)

1. This charter.
2. `agents/news_gated_momo/lessons.md` (append-only memory).
3. The day's news brief, `data/reports/news/latest.md`.
4. The algo's *preview* candidate list — the book's own `generate_orders` re-run
   read-only against the latest stored session. Labelled as a preview: at 21:40
   UTC today's bars are not collected yet, so this is last session's proposal
   set, and it indicates which names are in play rather than promising them.
5. The book's current holdings and the paper league's standing.

## Evaluation — pre-registered, no peeking, no re-registration

* **Evaluation date: 2027-02-01** (26 weeks from 2026-08-04).
* **Measure: the spread vs the frozen twin `momo_stopped`, net of costs, over
  the common window** (both books rebased to 1.00 on the first session on which
  both have equity).
* **Kill criterion: AI < twin at the evaluation → the AGENT LOOP is killed** —
  the daily gate session stops, the gate flag comes off the config, and the book
  continues as pure algo. The algorithm is never killed by this test.
* Interim numbers are reported for honesty and are **not** decision inputs. The
  correct action on a good or bad week before 2027-02-01 is none.

## Decisions logged at registration

* **D-A1a — the twin is the pre-existing live `momo_stopped` book** rather than a
  fresh clone. It runs the identical algorithm and already has a forward record;
  a second identical clone would burn a book slot to answer a question the
  existing one already answers. The cost is a 7-session inception gap
  (twin 2026-07-28, AI 2026-08-04), which is why every spread in
  `data/reports/agentic/` is computed on the **common window**, never on raw
  inception-to-date returns.
* **D-A1b — the gate is a FILE the strategy reads, not a live call inside the
  nightly.** A model call inside `generate_orders` would put an LLM, a network
  dependency and a quota on the critical path of the fatal league stage. A file
  written 50 minutes earlier by an independent, fail-soft session cannot break
  the nightly at all: no file means pure algo.
* **D-A1c — vetoes are recorded even when they bind on nothing.** The gate file
  is written whether or not the algo ends up proposing the named ticker, so the
  26-week review can separate "the agent was right" from "the agent was never
  tested".

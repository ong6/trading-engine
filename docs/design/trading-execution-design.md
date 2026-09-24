
# 🖥️ Trading Engine — Mock Execution & UI Tech Design

**Status: original tech design finalized 2026-07-16; implementation is now active.** Companion to
[trading-engine-design.md](trading-engine-design.md) (data + screener spec — **§12 defines the
current scope**) and the private sibling-store research note
`personal-data-store/research/trading-engine/retail-algo-trading-direction.md`.

This file preserves the original design and deferred-live-execution boundary. Statements below
that describe implementation as future work are historical; use
[`../how-it-works.md`](../how-it-works.md) for the current operating system and
[`../history/live-readiness-goal.md`](../history/live-readiness-goal.md) for the evidence and
execution-safety gates.

**Scope (revised 2026-07-16):** the current build is a **fully local mock trading system** on the
devbox — internal fill simulator, paper league, local UI. **No broker API, no Telegram, no
credentials, nothing inbound; only public data in and public derived data out (git).** The
historical moomoo integration notes remain in **Appendix A** for the deferred live phase (M5).
Elapsed time alone is not a gate: M5 requires mature positive prospective excess evidence plus
the recoverability, broker-paper reconciliation, independent risk, and disaster-recovery gates
in the current live-readiness goal.

## 0 · Settled decisions

| Decision | Value |
|---|---|
| Execution (current build) | **Internal fill simulator** — no external broker. Simulated next-open fills + configurable slippage/cost model |
| Portfolios | **Paper league** (spec §12.4): N auto-traded strategy portfolios + benchmarks + **one human-traded discretionary portfolio via the ticket UI** |
| Topology | Everything **local to the devbox**; API and UI bind loopback only and are reached through an SSH tunnel. No Tailscale or application-auth complexity |
| Stack | **FastAPI** backend + **Next.js** frontend (unchanged) |
| Autonomy | Strategy portfolios trade **fully automatically** (they're evidence generators); the discretionary portfolio is **manual approval per ticket** (it trains the real process) |
| Notifications | **Local only**: UI badges + daily `data/reports/` + journal lines. Telegram deferred to M5 |
| Reference notional | S$50k (~US$39k) per portfolio, so league results read directly as "what this would have done with my capital" |
| Cadence | Deterministic Sunday revalidation (§6); any refinement requires a separate explicit human decision and pre-registration |
| Real money | **Deferred (M5)** — Appendix A. Nothing in the current build can place a real order, by construction |

## 1 · Architecture — one box, three loops

```
DEVBOX (loopback services; SSH-tunnel access; public data in, conditional git out — zero secrets)
│
│  NIGHTLY LOOP (cron, post-US-close)
│    collect.py (full-universe EOD + point-in-time snapshots)
│    → market_date.py (breadth + paper-ledger continuity gate)
│    → screen.py → actions.py → league.py (paper fills and portfolio step)
│    → frozen forward reviews + E1 forward record
│    → sync.py (stage/commit/push data/ when an upstream is configured)
│    → queue_runner.py (intraday/signals/earnings; Friday fundamentals)
│
│  IDLE LOOP (queue_runner: one store-writing job or ≤ 8 isolated read-only
│             replay workers; network collectors lease only for checkpoints;
│             nice 19, load/RAM/disk guards — spec §12.7)
│    backtest farm: walk-forward, sweeps, robustness (spec §12.3 protocol)
│    → results table + data/reports/experiments/
│
│  INTERACTIVE LOOP (systemd services)
│    server/ FastAPI :8000 ── reads store/market.duckdb + data/
│    ui/ Next.js :3000     ── dashboard, league, ticket flow (discretionary paper)
│
└── store/market.duckdb (gitignored, grows: prices, intraday, fundamentals,
    snapshots, mock portfolios/orders/fills, experiment results)
```

Repo layout (broker/ shrinks to a simulator; everything else as before):

```
trading-engine/
  engine/         collect.py market_date.py screen.py queue_runner.py sync.py lib/
  sim/            fills.py (fill model: next-open, slippage, costs)
                  portfolio.py (positions, cash, R accounting)
                  league.py (runs all auto-portfolios daily)
                  strategies/ (one module per league member, pre-registered configs)
  farm/           backtest/ walkforward/ sweep/ experiments + research reports
  server/         main.py routes; market/league/paper read models; market/liquidity/exposure/
                  driver/scheduler/sector/XS/E1/walk-forward monitors; risk.py sizing.py tickets.py
  ui/             Next.js app
  data/           screens/ reports/ eod/ universe.csv _meta.json   ← commits
  store/          market.duckdb                                    ← gitignored
```

## 2 · The fill simulator — honest by design

- **Policy:** signals computed on close of day t → fills at **day t+1 open**, with slippage =
  max(half-spread estimate, 5bp) + 10bp round-trip cost — deliberately *worse* than the
  backtests' assumptions, so league results are conservative.
- Partial-fill/liquidity guard: a mock order may not exceed 1% of the name's median dollar
  volume (matters once the universe includes smaller names).
- **No same-bar fills, ever** — the look-ahead rule from the research, enforced in one place.
- Every fill is recorded with the exact bar + model inputs, so slippage assumptions can be
  re-litigated later against real fills (M5).

## 3 · UI — same five pages, mock-first

Persistent header: **MOCK banner** (always — there is no live mode in this build), regime badge,
data freshness. Pages:

1. **Dashboard** — today's screen (full-universe, liquid-large slice first), regime, league
   summary strip.
2. **League** *(new, replaces "account")* — equity curves per portfolio, rolling expectancy vs
   each sleeve's pre-registered decayed bar, drawdown, kill-criterion status, trade counts.
3. **Candidate → Ticket** — unchanged flow (chart, template checks, pre-filled ticket, 1%-risk
   sizing, playbook + emotion fields, risk-gate checklist) — but submits to the **discretionary
   paper portfolio** via the simulator.
4. **Positions & Orders** — all active portfolios, filterable; discretionary positions get
   distance-to-stop and unrealized R.
5. **Journal** — discretionary paper trades with R-multiples and on-plan flags; league events;
   review status.

## 4 · Risk gates — unchanged, and they apply to paper

`server/risk.py` enforces these 11 named controls on the **discretionary portfolio**:
`data_quarantine`, `stop_present`, `entry_anchored`, `notional_cap`, `sizing_1pct`,
`playbook_named`, `rr_at_least_2`, `max_open_risk_4r`, `earnings_window`, `regime_gate`, and
`circuit_breaker`. Paper is where the process gets trained, so the controls run for real.
Auto-portfolios get only the structural controls encoded by their strategy, such as sizing and
configured regime variants; their point is to test strategies, not to practice discretionary
discipline. Every submit writes an audit record.

## 5 · What replaced the safety model

There is no PAPER/LIVE toggle in this build — **there is no LIVE**. The simulator cannot reach a
broker; that's the safety model. Appendix A's 2026-07-15 in-UI toggle is retained as historical
design context and is superseded by the current live-readiness goal. Any future authorization
must be a short-lived server-side lease bound to one account, immutable release, strategy hash,
and capital ceiling; startup and restart remain submission-disabled.

## 6 · Weekly revalidation and explicit review (deterministic and local)

Sunday cron runs `engine/run_weekly_walkforward.sh`: it enqueues one replay for every eligible
active book, drains the resource-capped queue, and rebuilds the walk-forward reports. The former
`/watchlist-scan` + `/trading-review` model loop was retired on 2026-08-18 and is not an unattended
dependency. Any later model-assisted review is advisory and report-only. Refinement rules stand:
changes only at explicit reviews, one at a time, justified by prospectively declared evidence
rather than last week's P&L; every sleeve keeps its pre-registered decayed expectation and kill
criterion—breach means human kill review before redesign. League portfolios that die stay visible
in the league table (tombstoned): negative results are results.

## 7 · Build phases (mirrors spec §12.6)

| Phase | Deliverable | Exit criteria |
|---|---|---|
| **M0** | Scaffold + full-universe EOD collect (max history) + nightly cron | `_meta.json` shows a clean nightly run over ~4k+ names |
| **M1** | Full-universe screener + regime + point-in-time snapshots + sync | First `data/screens/<date>.md` pulled on the laptop |
| **M2** | Fill simulator + paper league + daily `league.md` | 5+ auto-portfolios trading daily, conservative fill model verified against §2 |
| **M3** | FastAPI + Next.js UI (loopback-only): dashboard, league, ticket flow | Discretionary paper trade end-to-end through risk gates |
| **M4** | Backtest farm + intraday/fundamentals mining | First pre-registered experiment report published; intraday archive accumulating |
| **M5** | *(deferred, gated)* real execution — Appendix A | Every strategy-evidence, recoverability, broker-paper, independent-risk, reconciliation, and recovery gate in the current live-readiness goal passes |

## 8 · Formerly-open questions — settled 2026-07-16

1. **League membership v1 (settled):** template-top5, template-top10-banded, dual-momentum,
   MR-overlay, regime-gated variants of each, EW + SPY benchmarks. Membership changes only at
   explicit human reviews, one at a time; scheduled revalidation cannot change membership.
2. **Intraday archive breadth (settled):** top-500 by dollar volume + watchlist names.
   Politeness caps per source; growth governed by the disk watchdog (engine spec §12.7).
3. **Access to :3000/:8000 (superseded by the current deployment boundary):** both services bind
   loopback only. SSH port-forwarding is the supported access path; do not expose either port
   directly to an intranet or the public internet.

---

## Appendix A · Historical M5 provider notes — moomoo, verified 2026-07-15

These provider facts and the original safety sketch are retained for provenance. Reverify every
broker capability, rate limit, platform requirement, and account restriction against current
official documentation before implementation. This appendix is not an authorization or current
security design; [`../history/live-readiness-goal.md`](../history/live-readiness-goal.md) records the gates a future execution plan inherits.

- **Host:** a personal machine only (small SG VPS ~US$6–12/mo or home mini PC) — never company
  hardware: broker credentials on corp infra = policy + inspection risk, corp egress
  filtering/TLS interception already observed (Stooq blocked, pip MITM'd), and the kill switch
  must not depend on corp VPN access. UI via personal Tailscale.
- **moomoo OpenAPI is not REST:** everything goes through **OpenD**, a gateway daemon
  (Command Line flavor, official Ubuntu support; TCP 11111 localhost) consumed by the
  `moomoo-api` Python SDK (PyPI ≥10.8.6808; forced minimum-version upgrades happen).
- **First login per machine needs SMS** (`input_phone_verify_code` via OpenD console); steady
  state auto-relogin works with `login_pwd_md5`. One-time API Questionnaire in the app.
- **SG accounts:** US stocks/ETFs fully API-tradable (SGX is not); order types
  limit/market/stop/stop-limit/trailing, TIF DAY/GTC/GTD, sessions RTH/ETH/OVERNIGHT
  (overnight = limit only). `unlock_trade` needed for REAL only. Use the **new US paper backend**
  (legacy being phased out). Rate limits per 30s: place 15 · modify/cancel 20 · order_list 10 ·
  snapshot 60 · unlock 10; order/fill push via `TradeOrderHandlerBase`/`TradeDealHandlerBase` —
  consume pushes, never poll.
- **Data:** US real-time L1+depth currently free promotionally for SG (revocable); subscription
  quota 100–300 symbol-type pairs at this asset level.
- **Historical safety sketch (superseded):** in-UI PAPER↔LIVE toggle, asymmetric — LIVE requires
  typed `LIVE` + server-side `unlock_trade` + per-order typed-ticker confirmation, logged +
  notified, **auto-reverts to PAPER after 24h inactivity**; back to PAPER is one unguarded click
  ("Kill & cancel" option). Secrets in `.env` (chmod 600, gitignored), never in the repo, never
  returned by any endpoint.
- **Telegram** (send-only v1): fills, env switches, circuit breaker, stale data, OpenD-needs-SMS;
  v2 option = inline approve/reject via tailnet-only webhook.
- **Current gate:** a frozen strategy must establish mature positive prospective excess against
  its proper control. A reviewed release must also pass recoverability, at least one uninterrupted
  month of broker-paper reconciliation, independent fail-closed risk controls, fault injection,
  and disaster-recovery drills. Only a separate explicit human review may authorize one immutable
  release, strategy, account, and minimum capital ceiling. See the live-readiness goal for the
  complete criteria and staged capital progression.

# P22 round-4 rehearsal transcripts

Captured disposable-store evidence from the round-4 acceptance run. The deployment
schedule remains October 18, with production D0 October 19. The legacy rehearsal
used a temporary D0 of October 5 to cross the boundary with captured sessions.

## rehearsal-legacy.txt

```text
Captured snapshot: through 2026-10-07; disposable checkpoint: 2026-10-02
Pre-D0 P15 evidence: passed; existing source-revised labels: 458
Migration: {"status": "migrated", "d0": "2026-10-05", "portfolio_count": 33, "break_count": 33, "reserved_order_id": 1774, "first_fetched_at_backfill": 21019293, "routing_changes": []}
Pre-D0 equity checkpoints unchanged; all routes preserved: 33
[league] ACCOUNT_STATUS ok; legacy_day_committed=true; completed_accounts=0
[league] 2026-10-05: fills=63 rejected=0 still_pending=0 new_orders=6 divs=1/$1.16 → $REHEARSAL_ROOT/data/reports/league.md
P15 window: 2026-10-05 {"status": "completed", "filled": 10, "rejected": 0, "pending": 0, "restored": 0, "queued": 8, "counterfactual_labels": 0, "marks": {"p15_ai_ranked": {"equity": 10066.968301385328, "cash": 982.6650637638613, "n_positions": 7, "carried": []}, "p15_rule_control": {"equity": 10170.329536273655, "cash": 402.09940074432996, "n_positions": 9, "carried": []}, "p15_hybrid_veto": {"equity": 10158.482860067274, "cash": 322.3825817384207, "n_positions": 8, "carried": []}}}
P15 validation: passed 2026-10-05
[league] WARN 1 position(s) in 1 book(s) marked at a CARRIED close on 2026-10-06 — the name printed no bar:
[league]   high_52wk: WBD
[league] ACCOUNT_STATUS ok; legacy_day_committed=true; completed_accounts=0
[league] 2026-10-06: fills=6 rejected=0 still_pending=0 new_orders=5 divs=1/$1.79 carried_marks=1 → $REHEARSAL_ROOT/data/reports/league.md
P15 window: 2026-10-06 {"status": "completed", "filled": 8, "rejected": 0, "pending": 0, "restored": 0, "queued": 4, "counterfactual_labels": 0, "marks": {"p15_ai_ranked": {"equity": 9969.254027547971, "cash": 3240.3196909862145, "n_positions": 5, "carried": []}, "p15_rule_control": {"equity": 9817.123724823672, "cash": 402.09940074432996, "n_positions": 9, "carried": []}, "p15_hybrid_veto": {"equity": 9831.123059683381, "cash": 39.37981499125419, "n_positions": 9, "carried": []}}}
P15 validation: passed 2026-10-06
[league] WARN 1 position(s) in 1 book(s) marked at a CARRIED close on 2026-10-07 — the name printed no bar:
[league]   high_52wk: WBD
[league] ACCOUNT_STATUS ok; legacy_day_committed=true; completed_accounts=0
[league] 2026-10-07: fills=5 rejected=0 still_pending=0 new_orders=4 carried_marks=1 → $REHEARSAL_ROOT/data/reports/league.md
P15 window: 2026-10-07 {"status": "completed", "filled": 4, "rejected": 0, "pending": 0, "restored": 0, "queued": 14, "counterfactual_labels": 0, "marks": {"p15_ai_ranked": {"equity": 9901.08104064001, "cash": 147.5761758411245, "n_positions": 6, "carried": []}, "p15_rule_control": {"equity": 9711.61603477507, "cash": 402.09940074432996, "n_positions": 9, "carried": []}, "p15_hybrid_veto": {"equity": 9693.567808982072, "cash": 39.37981499125419, "n_positions": 9, "carried": []}}}
P15 validation: passed 2026-10-07
Post-D0 fills and fees: [["momo_stopped", 15, 5.890000000000001], ["mr_overlay", 7, 9.22], ["mr_overlay_gated", 7, 9.22], ["p15_ai_ranked", 15, 5.550000000000001], ["p15_hybrid_veto", 4, 1.6099999999999999], ["p15_rule_control", 3, 1.1099999999999999], ["pead_ear", 3, 1.22], ["template_top10_banded", 15, 5.760000000000001], ["template_top10_banded_gated", 15, 5.760000000000001], ["template_top5", 6, 3.67], ["template_top5_gated", 6, 3.67]]
Evaluation clocks restarted: {"adaptive_mr": "2026-10-05", "adaptive_mr_frozen": "2026-10-05", "agentic_alloc": "2026-10-05", "agentic_alloc_frozen": "2026-10-05", "daily_opportunity_agent_v1": "2026-10-05", "discretionary": "2026-10-05", "dual_momentum": "2026-10-05", "dual_momentum_gated": "2026-10-05", "earnings_context_pead": "2026-10-05", "ew_benchmark": "2026-10-05", "ew_trend_gated": "2026-10-05", "ew_voltarget": "2026-10-05", "high_52wk": "2026-10-05", "low_vol": "2026-10-05", "macro_composite": "2026-10-05", "momo_stopped": "2026-10-05", "mr_overlay": "2026-10-05", "mr_overlay_gated": "2026-10-05", "multi_asset_trend": "2026-10-05", "news_gated_momo": "2026-10-05", "p15_ai_ranked": "2026-10-05", "p15_hybrid_veto": "2026-10-05", "p15_rule_control": "2026-10-05", "pead_ear": "2026-10-05", "sector_momentum": "2026-10-05", "spy_benchmark": "2026-10-05", "stop_tuner_turtle": "2026-10-05", "template_top10_banded": "2026-10-05", "template_top10_banded_gated": "2026-10-05", "template_top5": "2026-10-05", "template_top5_gated": "2026-10-05", "turtle_breakout": "2026-10-05", "xs_momentum_12_1": "2026-10-05"}
Pre-D0 fill fees: zero; post-D0 accounting uses original routes.
```

## rehearsal-rollback.txt

```text
Rollback source: bc6ff7de4dd388dfff6a728fe9a60fad565f501f
Rollback P15 revision: 13
Restored complete pre-migration store: byte-identical
Revision-13 HTTP /health: {"ok":true,"status":"ok","db_readable":true}
Revision-13 HTTP /meta: passed; payload retained
Restored store still byte-identical after main health/meta checks
Revision-13 restored-store P15 validation passed; 0 pending book windows
Main tests/test_p15_registration.py: 5 passed (rollback-registration.txt)
Rehearsal used isolated processes; no units installed or changed.
Removed release checkout and every round-4 disposable store; no rehearsal process remains.
```

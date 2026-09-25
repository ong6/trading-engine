# Prompt review, 2026-09-26

Review of the live model prompts in `server/agent_model_client.py` and their callers. Live prompts
are bound to frozen cohorts and are **not edited**. Each finding says what the next prompt version
must do. P15's scoring prompt applies these rules from its first version; P16 W0 re-runs this review
and ships `prompt-v2` for its challengers.

| # | Where | Problem | Next version |
|---|---|---|---|
| 1 | `OPPORTUNITY_INSTRUCTIONS` and `daily_opportunity_execution.py` (`MIN_CONFIDENCE`, template, earnings, max positions) | `confidence` is "from 0 through 1" with no definition. The code silently drops swings below 0.65, non-template names, names near earnings, and entries beyond 3 positions. The model never learns the thresholds or which names cannot trade | Define the probability exactly (horizon, entry basis, cost, benchmark), add an expected-excess field, and pass `tradeable` and `reason` for each candidate |
| 2 | `daily_opportunity_runner.py` input (`"execution_authority": "none"`) and the "research component" framing | The model is told it has no authority, yet its swings become simulator orders | State the true objective: picks are traded next open in a long-only simulator book, judged against SPY and a rule control; "ignore" is right when expected excess ≤ 0 |
| 3 | `hourly_opportunity_observer.py` (`task` swapped to `rapid_catalyst_watch` or `catalyst_and_structure_review`) | Intraday observers reuse the nightly prompt, including "daily" and 1–20 session horizons; the task labels are never explained, and quote age is never stated | A separate instruction per cadence: decision time, quote freshness, entry basis, primary horizon |
| 4 | Proposal role (`INSTRUCTIONS`) | The model picks `max_notional` and buy or sell, which contradicts code-owned sizing and the long-only rule; `no_action` is listed first | Drop `max_notional`, long-only, a symmetric decision list |
| 5 | Veto role | No criterion for allow versus veto; "cannot suppress sell orders" sits beside a bare veto verb | Replaced by P15's hybrid rule (veto when `expected_excess_bp_5 < 0`) |
| 6 | Trade tool role | A second call only echoes fields from the first: a failure point with no judgement | Deterministic code submits directly; keep model calls only where they decide something (P15 pre-open keep/cancel) |
| 7 | All roles | Long repeated "no strategy, risk, execution, broker … authority" disclaimers crowd the task | One sentence on authority, one on untrusted input text |

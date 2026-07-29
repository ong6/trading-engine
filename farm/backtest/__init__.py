"""Historical-backtest farm (design §12.3).

Replays the league's EXACT live strategy code over historical windows on scratch
copies of the store. Three pieces:

  hist_screen.py  vectorized point-in-time re-computation of `screen_results`
  replay.py       per-(book, window) scratch build + real league day-step loop
  stats.py        CAGR / vol / Sharpe / maxDD from a replay's sim_equity series
  report.py       the markdown reports under data/reports/backtests/

Nothing in this package runs in the nightly. The live store is opened read-only
(or read-only in effect — see replay.build_scratch) and every write lands in a
scratch DB that the job deletes when it finishes.
"""

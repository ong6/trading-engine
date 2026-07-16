"""M2 — internal fill simulator + paper league (spec §12.4, execution design §2).

An offline, network-free paper-trading layer over the engine's DuckDB store: a
fleet of pre-registered mock portfolios auto-traded through an honest fill model
(t+1 open, slippage, liquidity guards) to build forward out-of-sample evidence.
Reads prices/screen_results read-only; writes only its own sim_* / portfolios
tables.
"""

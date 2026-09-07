# Capital sensitivity — `spy_benchmark` / `5y`

_Every row is a complete strategy replay. Returns were not rescaled from another account size. This is paper research, not authorization for live trading._

Evidence class: `fixed_etf_history` · fill model `v4` · source `0e1f682e34fa96e32363c09c00a96c7699ac8aa44364081327c82a0579ab2262` · data `b1b031ac37c5b658034fd5b6234fdbe61facab5cba9cdd4afb1159c542fa3785`.

Capacity observations are bounds at the sampled account sizes, not an interpolated or guaranteed trading capacity.

- `baseline_v1`: Largest tested capital with zero capacity rejects: **$10,000,000**; first tested capital with a capacity reject: **none in grid**.
- `cost_2x_v1`: Largest tested capital with zero capacity rejects: **$10,000,000**; first tested capital with a capacity reject: **none in grid**.

| Profile | Start | Return | Max DD | Fills | Total rejects | Capacity rejects | Rejected notional | p95 participation | Max participation | Turnover | Market cost $ | Total cost $ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `baseline_v1` | $10,000 | 83.04% | -24.02% | 1 | 0 | 0 | $0 | 0.00% | 0.00% | 0.99× | $10 | $10 |
| `baseline_v1` | $39,000 | 83.04% | -24.02% | 1 | 0 | 0 | $0 | 0.00% | 0.00% | 0.99× | $39 | $39 |
| `baseline_v1` | $100,000 | 83.04% | -24.02% | 1 | 0 | 0 | $0 | 0.00% | 0.00% | 0.99× | $99 | $99 |
| `baseline_v1` | $250,000 | 83.04% | -24.02% | 1 | 0 | 0 | $0 | 0.00% | 0.00% | 0.99× | $247 | $247 |
| `baseline_v1` | $1,000,000 | 83.04% | -24.02% | 1 | 0 | 0 | $0 | 0.00% | 0.00% | 0.99× | $988 | $988 |
| `baseline_v1` | $10,000,000 | 83.04% | -24.02% | 1 | 0 | 0 | $0 | 0.04% | 0.04% | 0.99× | $9,881 | $9,881 |
| `cost_2x_v1` | $10,000 | 82.94% | -24.04% | 1 | 0 | 0 | $0 | 0.00% | 0.00% | 0.99× | $20 | $20 |
| `cost_2x_v1` | $39,000 | 82.94% | -24.04% | 1 | 0 | 0 | $0 | 0.00% | 0.00% | 0.99× | $77 | $77 |
| `cost_2x_v1` | $100,000 | 82.94% | -24.04% | 1 | 0 | 0 | $0 | 0.00% | 0.00% | 0.99× | $198 | $198 |
| `cost_2x_v1` | $250,000 | 82.94% | -24.04% | 1 | 0 | 0 | $0 | 0.00% | 0.00% | 0.99× | $494 | $494 |
| `cost_2x_v1` | $1,000,000 | 82.94% | -24.04% | 1 | 0 | 0 | $0 | 0.00% | 0.00% | 0.99× | $1,976 | $1,976 |
| `cost_2x_v1` | $10,000,000 | 82.94% | -24.04% | 1 | 0 | 0 | $0 | 0.04% | 0.04% | 0.99× | $19,761 | $19,761 |

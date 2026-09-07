# Capital sensitivity — `xs_momentum_12_1` / `5y`

_Every row is a complete strategy replay. Returns were not rescaled from another account size. This is paper research, not authorization for live trading._

Evidence class: `current_universe_survivor_biased` · fill model `v4` · source `0e1f682e34fa96e32363c09c00a96c7699ac8aa44364081327c82a0579ab2262` · data `b1b031ac37c5b658034fd5b6234fdbe61facab5cba9cdd4afb1159c542fa3785`.

Capacity observations are bounds at the sampled account sizes, not an interpolated or guaranteed trading capacity.

- `baseline_v1`: Largest tested capital with zero capacity rejects: **none**; first tested capital with a capacity reject: **$10,000**.
- `cost_2x_v1`: Largest tested capital with zero capacity rejects: **none**; first tested capital with a capacity reject: **$10,000**.

| Profile | Start | Return | Max DD | Fills | Total rejects | Capacity rejects | Rejected notional | p95 participation | Max participation | Turnover | Market cost $ | Total cost $ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `baseline_v1` | $10,000 | 194.77% | -36.95% | 2643 | 6 | 4 | $916 | 0.02% | 0.58% | 65.80× | $1,091 | $1,091 |
| `baseline_v1` | $39,000 | 204.06% | -37.07% | 3489 | 27 | 25 | $20,579 | 0.05% | 0.96% | 69.76× | $4,500 | $4,500 |
| `baseline_v1` | $100,000 | 200.23% | -37.07% | 3702 | 36 | 34 | $91,119 | 0.10% | 0.98% | 69.03× | $11,357 | $11,357 |
| `baseline_v1` | $250,000 | 192.86% | -37.98% | 3773 | 92 | 90 | $547,739 | 0.21% | 0.99% | 66.79× | $27,170 | $27,170 |
| `baseline_v1` | $1,000,000 | 155.62% | -38.08% | 3593 | 317 | 315 | $9,212,883 | 0.52% | 1.00% | 57.77× | $89,349 | $89,349 |
| `baseline_v1` | $10,000,000 | 128.41% | -30.10% | 2094 | 1736 | 1734 | $489,582,078 | 0.81% | 1.00% | 31.83× | $362,077 | $362,077 |
| `cost_2x_v1` | $10,000 | 174.03% | -36.98% | 2619 | 6 | 4 | $903 | 0.02% | 0.58% | 62.79× | $2,087 | $2,087 |
| `cost_2x_v1` | $39,000 | 182.22% | -37.33% | 3467 | 27 | 25 | $20,290 | 0.05% | 0.95% | 66.59× | $8,607 | $8,607 |
| `cost_2x_v1` | $100,000 | 181.29% | -37.34% | 3706 | 43 | 41 | $102,457 | 0.10% | 1.00% | 66.25× | $21,850 | $21,850 |
| `cost_2x_v1` | $250,000 | 175.31% | -37.90% | 3767 | 91 | 89 | $520,108 | 0.21% | 0.97% | 64.28× | $52,373 | $52,373 |
| `cost_2x_v1` | $1,000,000 | 140.60% | -38.52% | 3597 | 303 | 301 | $8,507,086 | 0.52% | 1.00% | 56.09× | $174,012 | $174,012 |
| `cost_2x_v1` | $10,000,000 | 126.11% | -30.27% | 2099 | 1730 | 1728 | $486,726,451 | 0.81% | 1.00% | 31.72× | $722,055 | $722,055 |

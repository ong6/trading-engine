# Capital sensitivity — `sector_momentum` / `5y`

_Every row is a complete strategy replay. Returns were not rescaled from another account size. This is paper research, not authorization for live trading._

Evidence class: `fixed_etf_history` · fill model `v4` · source `0e1f682e34fa96e32363c09c00a96c7699ac8aa44364081327c82a0579ab2262` · data `b1b031ac37c5b658034fd5b6234fdbe61facab5cba9cdd4afb1159c542fa3785`.

Capacity observations are bounds at the sampled account sizes, not an interpolated or guaranteed trading capacity.

- `baseline_v1`: Largest tested capital with zero capacity rejects: **$1,000,000**; first tested capital with a capacity reject: **$10,000,000**.
- `cost_2x_v1`: Largest tested capital with zero capacity rejects: **$1,000,000**; first tested capital with a capacity reject: **$10,000,000**.

| Profile | Start | Return | Max DD | Fills | Total rejects | Capacity rejects | Rejected notional | p95 participation | Max participation | Turnover | Market cost $ | Total cost $ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `baseline_v1` | $10,000 | 87.22% | -17.17% | 175 | 1 | 0 | $0 | 0.00% | 0.00% | 40.40× | $404 | $404 |
| `baseline_v1` | $39,000 | 87.30% | -17.18% | 205 | 0 | 0 | $0 | 0.00% | 0.01% | 40.56× | $1,582 | $1,582 |
| `baseline_v1` | $100,000 | 87.31% | -17.18% | 212 | 1 | 0 | $0 | 0.01% | 0.02% | 40.57× | $4,057 | $4,057 |
| `baseline_v1` | $250,000 | 87.31% | -17.18% | 216 | 0 | 0 | $0 | 0.03% | 0.06% | 40.57× | $10,142 | $10,142 |
| `baseline_v1` | $1,000,000 | 87.31% | -17.18% | 217 | 0 | 0 | $0 | 0.11% | 0.23% | 40.57× | $40,570 | $40,570 |
| `baseline_v1` | $10,000,000 | 103.14% | -14.76% | 194 | 18 | 18 | $74,630,631 | 0.61% | 0.98% | 34.51× | $345,137 | $345,137 |
| `cost_2x_v1` | $10,000 | 81.43% | -17.28% | 174 | 0 | 0 | $0 | 0.00% | 0.00% | 39.68× | $794 | $794 |
| `cost_2x_v1` | $39,000 | 81.52% | -17.29% | 205 | 0 | 0 | $0 | 0.00% | 0.01% | 39.86× | $3,109 | $3,109 |
| `cost_2x_v1` | $100,000 | 81.52% | -17.29% | 212 | 1 | 0 | $0 | 0.01% | 0.02% | 39.87× | $7,974 | $7,974 |
| `cost_2x_v1` | $250,000 | 81.52% | -17.29% | 216 | 0 | 0 | $0 | 0.03% | 0.06% | 39.87× | $19,937 | $19,937 |
| `cost_2x_v1` | $1,000,000 | 81.52% | -17.29% | 217 | 0 | 0 | $0 | 0.11% | 0.22% | 39.87× | $79,748 | $79,748 |
| `cost_2x_v1` | $10,000,000 | 98.03% | -14.82% | 194 | 18 | 18 | $73,756,480 | 0.60% | 0.96% | 34.03× | $680,591 | $680,591 |

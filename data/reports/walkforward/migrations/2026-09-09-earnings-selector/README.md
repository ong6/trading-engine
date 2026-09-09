# 2026-09-09 earnings-selector migration evidence

This directory freezes both sides of the 18-book walk-forward refresh required after the
earnings-selector source correction changed the protected research fingerprint. It is retained
evidence, not an input to the current walk-forward report or scheduler.

- `before/` is the last active cohort from source
  `44641be995d3b1dda59732f52076138b40d983d94eda22211dbae17a17a5d82f` and data snapshot
  `d16f6337aff010dd78090410db5786ac468e0be0f85aa8ff87932d069f572cbd`.
- `after/` is the frozen replacement cohort from source
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53` and data snapshot
  `a3823b32b5f04344fb909d1fd72c6db6e27812752f8ec99ce8408ed28ff4d668`.
- The canonical `../../results/` directory continues to change during later scheduled refreshes;
  it is intentionally not used to reproduce this historical comparison.

Run the retained audit from the repository root:

```console
.venv/bin/python tools/audit_walkforward_migration.py \
  data/reports/walkforward/migrations/2026-09-09-earnings-selector/before \
  data/reports/walkforward/migrations/2026-09-09-earnings-selector/after
```

The expected result is exit 1 with 18 artifacts compared, none missing, and 34 unexpected paths.
Exit 1 is intentional: eleven screen-driven books have a one-row screen-count change plus timing
drift, and `xs_momentum_12_1` has twelve sub-display-precision economic differences. The review and
cause are recorded in `BUILDLOG.md`; rounded reports, rankings, and decisions did not change.

The regression test hashes every retained JSON path and byte before asserting that audit result.
Its aggregate retained-evidence digest is
`6584e73a7535ee1101ff58ffca990fab7f2e87d2cb0fce5cc7d20150f91aed24`.

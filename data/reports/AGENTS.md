# data/reports/ — agent notes

Generated evidence written by the producers; [`README.md`](README.md) maps every family and names
its live authority.

Local rules: do not hand-edit generated reports; fix the producer and let it regenerate. A report
is evidence, never authority to promote a book or trade: `GET /meta` owns current validity. Never
stash, revert or commit pipeline outputs as part of a code change; the metrics snapshot under
`metrics/` is the exception, published by `python -m tools.metrics_snapshot --check-budget`.

Search: the root `.ignore` keeps `data/screens/`, every `results/` and `cells/` folder under
`data/` and the lock files out of ripgrep-based tools. The same filter for `git grep`:

```bash
git grep PATTERN -- . ':!data/screens' ':(exclude,glob)data/**/results/**' \
  ':(exclude,glob)data/**/cells/**' ':!uv.lock' ':!ui/package-lock.json'
```

# ops/ — agent notes

Host operations data.

- `jobs.toml` is the job registry: each scheduled job's argv, unit `exec_start`, locks, timeouts,
  retries and receipt retention. Units are rendered from it; change it, re-render, land, then run
  `python -m tools.install_automation --apply` ([`../docs/change/deploy.md`](../docs/change/deploy.md)).

Local rules: a job change ships with its unit and `server/schedule-contract.json` entry in the same
commit; never hold the live store outside a declared window.

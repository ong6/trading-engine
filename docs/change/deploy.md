# Deploy

Merged `main` with green CI is deployed by the deployer (see the interim note below while it runs
in dry run). Workers test ([`testing.md`](testing.md)) and land branches; they never deploy by hand.

## Land a branch

```bash
python -m tools.land BRANCH --reason-file reason.txt --push
```

A change to a file pinned by a registration needs a re-pin: `python -m tools.repin --check`, then
`python -m tools.repin --reason-file F`. With no reason file inside an undeployed revision it
refreshes the pins. Never change a registered value.

## Interim: the deployer runs in dry run

The nightly no longer pulls code, and until the orchestrator switches the deployer timer to
`--execute`, nothing deploys code automatically. After `python -m tools.land BRANCH --push`, the
orchestrator deploys by hand: run `python -m tools.auto_deploy --execute` once, or fast-forward the
live checkout and run `python -m tools.install_automation --apply`. Once the timer runs with
`--execute`, merged to `main` with green CI is deployed. (Edit this section when the switch happens.)

## The deployer

`trading-engine-auto-deploy.timer` runs `tools/auto_deploy.py` at :06, :21, :36 and :51 UTC.

1. Before changing anything it skips 14:05–14:35 and 22:30–03:00 UTC; while a producer lock,
   producer process or release transaction is active; when an engine timer or engine cron job is
   due within 15 minutes or an engine unit is running (`skipped:timer-soon`, `skipped:unit-active`);
   and when free space is below the 70 GiB store reserve (`skipped:low-disk`).
2. It takes the newest `main` commit whose GitHub `ci` run is green.
3. On a private worktree it runs `tools.deploy_gate` plus the registration and forward-record
   tests. A dependency, schema-migration or contract-version commit is `needs-human`: everything
   before it deploys, and that commit waits for a person, who releases it through
   `tools/release_deploy.py` (dry by default, `--execute` to mutate). A `needs-human` target is
   not re-checked until `main` moves (`skipped:refused-target`).
4. It fast-forwards the live checkout (rebasing data-only local commits). When a forward-record
   closure changed, it runs `--migrate-runtime-contract` after a digest-only rehearsal.
5. It runs `tools.install_automation --apply` (changed units; API or UI restart only when their
   code changed) and post-checks `/health`, `/ready` and `/meta`.
6. A failed post-check rolls back automatically. After `rolled-back` or a failed rollback it halts
   (`skipped:halted`) until a person checks and runs `python -m tools.auto_deploy --clear-halt`.

Decisions appear only under "Deployer" in the hourly digest; there are no other alerts. State lives in
`~/.local/state/trading-engine/auto-deploy/state.json`; receipts in `logs/job-runs/auto-deploy/`.
The nightly does not pull code; it takes only data-only commits.

## Operate the deployer

- **Switch to execute**: add `--execute` to the auto-deploy job's `argv` and `exec_start` in
  `ops/jobs.toml`, re-render the unit, land it, then run `python -m tools.install_automation --apply`.
- **Pause**: `systemctl --user stop trading-engine-auto-deploy.timer`.
- **Manual rollback**: restore reports from `auto-deploy/backups/<time>/`, run
  `git -C ~/trading-engine reset --keep <previous>`, then `python -m tools.install_automation --apply`,
  and check `/ready`.
- **Gate a tree by hand**: `.venv/bin/python -m tools.deploy_gate --check WORKTREE` writes a
  receipt named after `HEAD^{tree}`; exit 2 is a refusal (`refused_by` names the check), exit 3
  means the checkout was dirty or moved.

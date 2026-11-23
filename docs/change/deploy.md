# Deploy

Merged `main` with green CI is deployed by the deployer. Workers test ([`testing.md`](testing.md)) and land branches; they never deploy by hand.

## Land a branch

```bash
python -m tools.land BRANCH --reason-file reason.txt --push
```

A change to a file pinned by a registration needs a re-pin: `python -m tools.repin --check`, then
`python -m tools.repin --reason-file F`. With no reason file inside an undeployed revision it
refreshes the pins. Never change a registered value.

## The deployer

`trading-engine-auto-deploy.timer` runs `tools/auto_deploy.py` at :06, :21, :36 and :51 UTC.

1. Before changing anything it skips 14:05–14:35 and 22:30–03:00 UTC; while a producer lock,
   producer process or release transaction is active; when an engine timer or engine cron job is
   due within 15 minutes or an engine unit is running (`skipped:timer-soon`, `skipped:unit-active`);
   and when free space is below the 70 GiB store reserve (`skipped:low-disk`).
2. It takes the newest `main` commit whose GitHub `ci` run is green.
3. On a private worktree it runs `tools.deploy_gate` plus the registration and forward-record
   tests. A dependency, schema-migration or contract-version commit is `needs-human`: everything
   before it deploys, and that commit waits to be released through `tools/release_deploy.py`
   (dry by default, `--execute` to mutate). Each release transaction keeps its state under
   `~/.local/state/trading-engine/releases/<name>/` (its `state.json` phase and its store backup
   in `recovery/`). A `needs-human` target is not re-checked until `main` moves
   (`skipped:refused-target`).
4. It fast-forwards the live checkout (rebasing data-only local commits). When a forward-record
   closure changed, it runs `--migrate-runtime-contract` after a digest-only rehearsal.
5. It runs `tools.install_automation --apply` (changed units; API or UI restart only when their
   code changed) and post-checks `/health`, `/ready`, `/meta` and the automation audit.
6. A failed post-check rolls back automatically. A rolled-back target is refused until `main`
   moves; newer green commits still deploy.

## Self-heal

- After every verified deploy the deployer records the last verified commit. Its first run trusts
  the deployed checkout, and a healthy hand deploy is adopted.
- While it moves the checkout it leaves an in-flight marker. Each run first converges: a crashed
  deploy, a failed rollback, or unhealthy code that was never verified is brought back to the last
  good commit by restoring the reports, `git reset --keep` (else a hard reset of tracked files;
  untracked store files are untouched and a `refs/auto-deploy/pre-recovery-*` ref keeps every
  commit), re-applying data-only commits, `install_automation --apply` and a health check.
- Failed recoveries retry with backoff from 15 minutes to 4 hours; after three it clears failed
  engine units and restarts the API and UI.
- Dry runs report `would-recover` and never act. `--drill-rollback` (with `--execute`) proves the
  rollback path.
- There are no notifications: decisions and recovery actions appear in the receipts and the hourly
  digest.

Each run records one decision: `deployed`, `would-deploy` (dry run), `skipped:<reason>`
(`window`, `producer-running`, `release-transaction`, `timer-soon`, `unit-active`, `low-disk`,
`refused-target`, ...), `needs-human:<reason>`, `rolled-back`, `recovered`, `would-recover` or
`recovery-failed`. Decisions appear under "Deployer" in the hourly digest. State lives in
`~/.local/state/trading-engine/auto-deploy/state.json`; receipts in `logs/job-runs/auto-deploy/`.
The nightly does not pull code; it takes only data-only commits.

## Operate the deployer

- **Dry run by hand**: `python -m tools.auto_deploy` (without `--execute`) reports what the timer
  would do and changes nothing.
- **Release directories are load-bearing**: the live `.venv` links into the newest release's
  `prepared/` environment under `~/.local/state/trading-engine/releases/`. Only `recovery/` may be
  deleted (the retention job does that); never delete a release directory.
- **Pause**: `systemctl --user stop trading-engine-auto-deploy.timer`.
- **Manual rollback**: restore reports from `auto-deploy/backups/<time>/` (the newest two are
  kept; see [local retention](../operate/how-it-works.md#local-retention)), run
  `git -C ~/trading-engine reset --keep <previous>`, then `python -m tools.install_automation --apply`,
  and check `/ready`.
- **Gate a tree by hand**: `.venv/bin/python -m tools.deploy_gate --check WORKTREE` writes a
  receipt named after `HEAD^{tree}`; exit 2 is a refusal (`refused_by` names the check), exit 3
  means the checkout was dirty or moved.

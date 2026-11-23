# Deploy

Merged `main` with green CI is deployed by the deployer. Workers test
([`testing.md`](testing.md)) and land branches; they never deploy by hand.

## Land a branch

```bash
python -m tools.land BRANCH --reason-file reason.txt --push
```

A change to a file pinned by a registration needs a re-pin: `python -m tools.repin --check`, then
`python -m tools.repin --reason-file F`. With no reason file inside an undeployed revision it
refreshes the pins. Never change a registered value.

## The deployer

`trading-engine-auto-deploy.timer` runs `tools/auto_deploy.py` at :06, :21, :36 and :51 UTC. It
stays in dry run until the orchestrator switches it to execute.

1. It skips 14:05–14:35 and 22:30–03:00 UTC, and while a producer lock, producer process or
   release transaction is active.
2. It takes the newest `main` commit whose GitHub `ci` run is green.
3. On a private worktree it runs `tools.deploy_gate` plus the registration and forward-record
   tests. Dependency, schema-migration and contract-version changes are refused as needs-human;
   those go through `tools/release_deploy.py` (dry by default, `--execute` to mutate).
4. It fast-forwards the live checkout (rebasing data-only local commits). When a forward-record
   closure changed, it runs `--migrate-runtime-contract` after a digest-only rehearsal.
5. It runs `tools.install_automation --apply` (changed units; API or UI restart only when their
   code changed) and post-checks `/health`, `/ready` and `/meta`.
6. A failed post-check rolls back automatically.

Decisions appear under "Deployer" in the hourly digest. State lives in
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

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

`trading-engine-auto-deploy.timer` runs `tools/auto_deploy.py` at :15, :22, :45 and :52 UTC:
the minutes between the publish-on-change starts (:12 and :42) whose 15-minute look-ahead stays
clear of them, two per half hour.

1. Before changing anything it skips 09:05–09:35 New York time (the pre-open; 14:05 UTC in
   winter, 13:05 in summer) and 22:30–03:00 UTC; while a producer lock,
   producer process or release transaction is active; when an engine timer or engine cron job is
   due within 15 minutes or an engine unit is running (`skipped:timer-soon`, `skipped:unit-active`);
   and when free space is below the 70 GiB store reserve (`skipped:low-disk`).
2. It takes the newest `main` commit whose GitHub `ci` run is green.
3. On a private worktree it runs `tools.deploy_gate` plus the registration and forward-record
   tests. A dependency, schema-migration or contract-version commit is `needs-human`: everything
   before it deploys, and that commit waits to be released through `tools/release_deploy.py`
   (dry by default, `--execute` to mutate; a dry `rollback` reports `would-refuse` and the
   reason when `--execute` would refuse). Each release transaction keeps its state under
   `~/.local/state/trading-engine/releases/<name>/` (its `state.json` phase and its store backup
   in `recovery/`). A `needs-human` target is not re-checked until `main` moves
   (`skipped:refused-target`). A gate refusal (exit 2) is `needs-human:gate-refused`; a gate
   that cannot check (exit 3) or times out is `skipped:gate-cannot-check` or
   `skipped:gate-timeout`, and timed-out forward tests or check-environment builds are
   `skipped:forward-tests-timeout` or `skipped:check-venv-timeout`; all are retried on the next
   tick, and the third timeout in a row on one target makes it `needs-human`. A gate, test run
   or `uv` that cannot start (a missing interpreter) is `needs-human`.
4. It fast-forwards the live checkout (rebasing data-only local commits). When a forward-record
   closure changed, it runs `--migrate-runtime-contract` after a digest-only rehearsal.
5. It runs `tools.install_automation --apply` (changed units; API or UI restart only when their
   code changed) and post-checks `/health`, `/ready`, `/meta` and the automation audit.
6. A failed post-check rolls back automatically. A rolled-back target's code is refused
   (`skipped:refused-target`) until a green commit outside `data/` changes it; data-only pushes
   do not retry it. A rollback drill, or a target whose code is the deployed code, is not
   remembered this way; the memory is dropped once different code is deployed and verified, or
   a hand deploy of that code is adopted healthy.

## Self-heal

- After every verified deploy the deployer records the last verified commit. Its first run trusts
  the deployed checkout, and a healthy hand deploy is adopted.
- Before it moves the checkout it leaves an in-flight marker. Each run first converges: a crashed
  deploy, a failed rollback, or unhealthy code that was never verified is brought back to the last
  good commit by restoring the reports, `git reset --keep` (else a hard reset of tracked files;
  untracked store files are untouched, uncommitted `data/` edits are put back unless the reset
  changed that file, when the receipt's `data_kept` names the saved copy (the newest two saved
  sets are kept), and a
  `refs/auto-deploy/pre-recovery-*` ref keeps every commit), re-applying data-only commits,
  `install_automation --apply` and a health check.
- Failed recoveries retry with backoff from 15 minutes to 4 hours; after three it clears failed
  engine units and restarts the API and UI, unless a re-check just before finds the pre-open
  window or an engine start within 5 minutes (`heal_skipped` in the receipt).
- A recorded recovery (in-flight marker or failed recovery) may run in the 22:30–03:00 window
  and looks ahead 5 minutes instead of 15 for an engine start, so a broken host is not left for
  hours. It keeps the pre-open window (non-engine jobs that use the checkout run then) and
  still waits for producer locks, producer processes, a release transaction, a running engine
  unit and low disk. Unhealthy unverified code found only by the health probe is gated like a
  deploy.
- Dry runs report `would-recover` and never act. `--drill-rollback` (with `--execute`) proves the
  rollback path.
- There are no notifications: decisions and recovery actions appear in the receipts and the hourly
  digest.

Each run records one decision: `deployed`, `would-deploy` (dry run), `skipped:<reason>`
(`window`, `producer-lock:<file>`, `producer-running`, `release-transaction`, `timer-soon`,
`unit-active`, `low-disk`, `up-to-date`, `no-green-ci`, `refused-target`, `run-in-progress`,
`recovery-backoff`, `would-recover`, `gate-cannot-check`, `gate-timeout`,
`forward-tests-timeout`, `check-venv`, `check-venv-timeout`, ...), `needs-human:<reason>`
(`dependencies`, `schema-migration`, `contract-version:<family>`, `gate-refused`,
`gate-cannot-start`, `forward-tests`, `forward-tests-cannot-start`, `check-venv-cannot-start`,
a third `*-timeout` in a row, ...), `rolled-back`, `recovered` or `recovery-failed`. A skip at the first gate (window, lock, producer, release transaction,
low disk) adds `waiting_at_last_fetch`: how many `main` commits the private mirror's last fetch
has past the live checkout's base on `main`, as of the live checkout's last fetch (neither is
fetched before the gates pass). Decisions appear under "Deployer" in the hourly digest. State lives in
`~/.local/state/trading-engine/auto-deploy/state.json`; receipts in `logs/job-runs/auto-deploy/`.
The nightly does not pull code; it takes only data-only commits.

## Operate the deployer

- **Dry run by hand**: `python -m tools.auto_deploy` (without `--execute`) reports what the timer
  would do and changes nothing, `state.json` included. One run at a time holds `run.lock` in the
  state directory; a second exits `skipped:run-in-progress`.
- **Crontab during a release**: a release removes the whole crontab while the host is paused
  and restores it exactly as captured, external lines included, so those lines do not run
  meanwhile and a cron line added during the release is not kept.
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

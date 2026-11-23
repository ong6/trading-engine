# tools/ — agent notes

Operator and maintenance commands, run as `.venv/bin/python -m tools.<name>`. None of them takes
part in research execution.

- **Change and ship**: `affected_tests` (fast tier and CI plan), `land`, `repin`, `auto_deploy`
  (the deployer), `deploy_gate`, `release_deploy`,
  `install_automation`, `service_deploy`, `release_manifest`, `registration_identity`,
  `worktree_audit`, `lane` (lane worktrees), `public_hygiene` (+ `public_hygiene_pre_push.sh`).
  Deploy path: [`../docs/change/deploy.md`](../docs/change/deploy.md).
- **Operate**: `ops_digest` (hourly digest), `driver_watchdog`, `schedule_contract_check`,
  `stage_timings`, `check_invariants` with `invariants/`, `log_retention`, `prune_local`,
  `publish_snapshot`, `backup_database`, `verify_friday_postflight`, `run_job`, `metrics_snapshot`.
- **Data capture**: `free_sources`, `free_sec`, `free_sec_bulk`, `free_massive_minute`,
  `free_massive_options`, `free_frozen_archive`, `free_source_audit`, `sec_edgar_capture`,
  `market_data_source`, `provider_contracts` (recorded fixtures and the runtime-environment
  contract).
- **Evidence and review**: `p15_evidence_validation`, `agent_trial_register`,
  `backfill_agent_evaluation`, `audit_walkforward_migration`, `review_agent_*`,
  `adjudicate_agent_data_discrepancy`, `retire_books`, `sim_bench`.
- **One-shot migrations**: `migrate_*`, `initialize_agent_paper_book`, `convert_raw_payloads`; each
  is backup-gated.

Local rules: dry-run by default, mutate only with an explicit flag (`--apply`, `--execute`); never
hold the live store writer outside a declared window; no new operator CLI without a plan. Runbook:
[`../docs/operate/how-it-works.md`](../docs/operate/how-it-works.md).

# server/ — agent notes

The loopback API, the agent services and their registrations, and the systemd units and wrappers
that schedule them. The API never fills orders or steps the league: a ticket becomes a pending
order that the nightly step fills at the next open.

- **API**: `main.py` (FastAPI on `127.0.0.1:8000`, no auth, read-only GETs per request; a contended
  write returns 503), started by `run_server.sh`. `GET /meta` (`meta_projection.py`,
  `meta_snapshot.py`) is the live authority for producers, freshness, forward records, invariants
  and source control.
- **Read models**: `*_read_models.py` with `read_model_utils.py`, `request_memo.py` and
  `status_validation.py` back the GETs; `accounts_routes.py` is the account service (bearer
  auth); `db.py` opens per-request connections; `file_utils.py`, `json_utils.py` are helpers.
- **Monitors**: `*_monitor.py` (scheduler, driver, nightly, queue, miner, sweep, liquidity,
  exposure), `driver_log.py`, `scheduler_host.py`, `host_command.py`, `market_health.py`,
  `nightly_reports.py`, `friday_postflight.py`, `invariants_status.py`, `source_control.py`;
  `schedule_contract.py` checks `schedule-contract.json`, which declares every unit, timer and
  cron line allowed on the host.
- **Evidence projections**: `*_forward_status.py` (E1, sector, XS records) on
  `forward_contracts.py`; `walkforward_*.py` validate published walk-forward results.
- **Readiness and sources**: `*_readiness.py` with `readiness_common.py` gate new research on
  data coverage; `*_source.py` and `market_data_sources.py` are the exact-response adapters.
- **Agent services**: `daily_opportunity_*` (P8), `hourly_opportunity_observer.py` (P9),
  `p15_*` (scoring, pre-open, events), `p16_*` (challenger lab, filing reader; inert until W9b),
  `p7_*` (built, not activated), `agent_*` (evaluation, shadow, data capture, model client);
  `p16-*-prompt-*.txt` are the P16 model prompts.
- **Discretionary path and risk**: `ticket*.py`, `risk*.py`, `sizing.py`.
- **Registrations**: `p15-registration.json`, `p16-registration.json`, `p7-trial-registration.json`,
  `agent-*-registration.json`, `collection-policy.json`, `options-capture-manifest.json`. These
  are frozen contracts: never edit a registered value. A change to a pinned file needs a
  registration revision: `python -m tools.repin --check`, then `--reason-file F`
  ([`../docs/change/deploy.md`](../docs/change/deploy.md#land-a-branch));
  `python -m tools.registration_identity` verifies it.
- **Units**: `trading-engine-*.{service,timer}` and `massive-*.{service,timer}`, installed by
  `tools.install_automation` and declared in `schedule-contract.json`; change the manifest in the
  same commit as the unit. The other `run_*.sh` are wrappers the agent, scoring and archive
  units start.
- **Inert**: `broker_*` and `*_broker_adapter.py` (broker-paper adapters, the paper-authority
  state machine, the simulator and disabled live adapters) are built and frozen; no broker
  connection, credentials or real money on this host.

Local rules: no new endpoint, dashboard card or migration without a plan; the API stays on
loopback. Component map: [`../docs/architecture/architecture-reference.md`](../docs/architecture/architecture-reference.md#dashboard-and-api-boundaries).

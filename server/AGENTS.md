# server/ — agent notes

The loopback API, the agent services and their registrations, and the systemd units and wrappers
that schedule them. The API never fills orders or steps the league: a ticket becomes a pending
order that the nightly step fills at the next open.

- **API**: `main.py` (FastAPI on `127.0.0.1:8000`, no auth, read-only GETs per request; a contended
  write returns 503), started by `run_server.sh`. `GET /meta` (`meta_projection.py`,
  `meta_snapshot.py`) is the live authority for producers, freshness, forward records, invariants
  and source control.
- **Monitors**: `scheduler_monitor.py` and `driver_monitor.py`; `schedule-contract.json` declares
  every unit, timer and cron line allowed on the host.
- **Agent services**: `daily_opportunity_*` (P8), `hourly_opportunity_observer.py` (P9),
  `p15_*` (scoring, pre-open, events), `p16_*` (challenger lab, filing reader; inert until W9b),
  `p7_*` (built, not activated), `agent_*` (evaluation, shadow, data capture, model client).
- **Discretionary path and risk**: `tickets.py`, `ticket_store.py`, `risk*.py`, `sizing.py`.
- **Registrations**: `p15-registration.json`, `p16-registration.json`, `p7-trial-registration.json`,
  `agent-*-registration.json`, `collection-policy.json`, `options-capture-manifest.json`. These
  are frozen contracts: never edit a registered value. A change to a pinned file needs a
  registration revision: `python -m tools.repin --check`, then `--reason-file F`
  ([`../docs/change/deploy.md`](../docs/change/deploy.md#land-a-branch));
  `python -m tools.registration_identity` verifies it.
- **Units**: `trading-engine-*.service` / `.timer`, installed by `tools.install_automation` and
  declared in `schedule-contract.json`; change the manifest in the same commit as the unit.
- **Inert**: `broker_*` (broker-paper adapters and the paper-authority state machine) are built
  and frozen; no broker connection, credentials or real money on this host.

Local rules: no new endpoint, dashboard card or migration without a plan; the API stays on
loopback. Component map: [`../docs/architecture/architecture-reference.md`](../docs/architecture/architecture-reference.md#dashboard-and-api-boundaries).

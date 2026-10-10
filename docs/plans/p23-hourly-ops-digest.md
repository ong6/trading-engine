---
plan: P23
title: Hourly operations digest
status: active
opened: 2026-10-10
owner_decision: approved by the owner's 2026-10-10 request to review last night's run and improve logging and observability with an hourly collated log and a small SQLite metrics store
---

## Goal

An agent can answer "did the last night and day go fine, and what changed?" from one command,
without grepping five log formats. Each hour the past hour's unit runs, driver stages, API
probes and new warning/error lines are collated into one Markdown digest, and the numbers
(outcomes, durations, line and byte counts, signatures, probe latency, `/meta` statuses, disk
footprint) go into a small SQLite file for trend queries. High availability is not a goal.

## Why now

The 2026-10-10 review of the 10-09 nightly and overnight timers found: every stage and unit
exited 0 while real problems hid behind success (withheld P15 price-fetch records, a skipped
TradingView archive run, half the usual pre-market coverage, material price disagreements); the
verify-and-farm stage ran 1h48m with no way to see why; the user journal was volatile and
unreadable, so seven units had no readable output; the price verifier's evidence dump grew the
nightly log from ~600 to ~13,900 lines; nothing rotates in `logs/`.

## Scope

- `tools/ops_digest.py`: hourly collector and `--report` summary; writes only under `logs/ops/`.
- `server/trading-engine-ops-digest.{service,timer}` (:05 UTC hourly), registered in
  `tools/install_automation.py` and enabled with the other timers.
- `tests/test_ops_digest.py`; runbook section in `docs/how-it-works.md`.
- Host (outside the repo): persistent journald storage (30 days, 2 GB cap) so `journalctl --user`
  works for every unit; done 2026-10-10.

## Not in scope

Push alerts (owner decision 2026-10-02: failures are triaged on demand); changes to any
P15-registered file (the verifier dump and the fail-soft exits are listed under "Proposed, not
approved" in `scope.md` for the next registration revision); log rotation of existing files;
raw log text in SQLite; new API endpoints or UI.

## Done when

`systemctl --user list-timers trading-engine-ops-digest.timer` shows it active, and after the
next nightly `.venv/bin/python -m tools.ops_digest --report --hours 24` lists every unit run and
driver stage of the window with durations and outcomes.

## Budget

Two commits, under 900 lines; one session.

## Risks

The collector only reads; its outputs live in the gitignored `logs/ops/`. Rollback:
`systemctl --user disable --now trading-engine-ops-digest.timer` and delete `logs/ops/`.

# Add a strategy or experiment

Stub: the full path is written under [P25](../plans/p25-ship-autodeploy-cleanup.md) scope item 8.

Until then, the short version:

- Strategy logic, prompts, parameters, registrations, trial counts and results go to the private
  alpha repo. Only reusable, generic infrastructure lands here.
- Every strategy or experiment is pre-registered with a control, costs, sample rule and kill
  criterion before evidence accrues; the charter checklist is in
  [`../strategy-research-backlog.md`](../strategy-research-backlog.md#evidence-rules-for-the-next-candidate)
  and the study standard in [`../change/backtest-standard.md`](../change/backtest-standard.md).
- Historical studies use the shared backtest core (`farm/study/`); paper execution uses
  engine-owned accounts ([`../architecture/paper-account-contract.md`](../architecture/paper-account-contract.md)).

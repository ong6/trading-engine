"""Weekly walk-forward re-validation of every active league rule (design §12.3).

Feeds the Sunday review loop (execution design §6): "changes only at reviews,
one at a time, justified by walk-forward evidence not last week's P&L".

Four pieces:

  protocol.py  the FROZEN fold protocol — train/validate lengths, fold dates,
               which books are excluded and why
  runner.py    one queue job per book: one scratch store, one screen pass, then
               one independent replay per fold through the real league day-step
  report.py    data/reports/walkforward/ — per-book pages + the index
  grid.py      enumerate / enqueue the weekly grid (job kind 'walkforward')

Nothing here runs in the weekday nightly. The live store is opened read-only
(SELECT + COPY … TO parquet only); every write lands in a scratch DB the job
deletes when it finishes, or in data/reports/walkforward/.
"""

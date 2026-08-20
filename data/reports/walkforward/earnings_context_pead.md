# Earnings-Context PEAD (AI) — walk-forward re-validation

_`earnings_context_pead` · pead_ear · daily cadence · verdict **INERT — no result** · generated 2026-08-16T07:02:49+00:00_

## This book placed no trades, so it has no result

The replay ran without error across **6 fold(s)** and the book posted **zero fills** in every one of them. Its equity therefore sat at the reference notional for the whole span, and every statistic derived from that curve — return, drawdown, Sharpe, excess versus any benchmark — is an artefact of the book never trading, not a measurement of the rule.

**There is no verdict here and there should not be one.** A number computed over a flat line is not evidence, and this page previously carried one. Usually the cause is a config the strategy can never satisfy, or a strategy whose inputs do not exist over the replay window — check the params and the data floor before reading anything into this book.

See the exclusions section of [README.md](README.md).

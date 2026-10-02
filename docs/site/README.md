---
title: Product documentation
summary: The ordered page contract for the public, plain-language guide to the paper trading and research engine.
order: 0
section: Start here
---

# Product documentation

This directory is the site-rendering contract. Pages appear in the order below. Every published
page has a one-sentence summary, one of four section labels, and a source-path comment that points
reviewers back to the implementation or internal record.

The guide is written for a curious reader who does not know the engine’s internal plan codes. The
main pages explain the product first; the glossary translates codes when a reader needs to inspect
the internal plans.

| Order | Page | Section | Summary |
|---:|---|---|---|
| 1 | [The trading engine](index.md) | Start here | A paper-only system that collects market data, runs research, and tests whether AI decisions add value without risking real money. |
| 2 | [The daily cycle](daily-cycle.md) | How it works | A New York-time guide to the market checks, paper-book updates, AI scoring, and weekend maintenance that run automatically. |
| 3 | [Data and time](data.md) | How it works | The engine keeps source receipts and availability times so a decision can use only facts that truly existed at that moment. |
| 4 | [Paper books and the league](paper-books.md) | How it works | Paper books behave like portfolios with delayed fills and costs, while the league shows how each one compares with SPY. |
| 5 | [AI agents](ai-agents.md) | How it works | Models score and explain bounded choices, while deterministic code keeps control of data, risk, execution, and evaluation. |
| 6 | [How research earns a verdict](research-process.md) | Research | Ideas are frozen before testing, charged for every trial, checked on sealed data, and usually stopped rather than tuned. |
| 7 | [The shared backtest core](backtest-engine.md) | Research | One deterministic evaluator gives event and portfolio studies the same point-in-time data, fills, costs, benchmarks, and statistical checks. |
| 8 | [Evidence and reliability](evidence-and-reliability.md) | Operations | Frozen identities, validators, snapshots, backups, and stage timing make a result reproducible and a failure diagnosable. |
| 9 | [Operations](operations.md) | Operations | Locks, schedule checks, read-only fallbacks, verified backups, and on-demand investigation keep unattended paper research recoverable. |
| 10 | [Roadmap](roadmap.md) | Start here | Near-term work connects private research to live paper observation and speeds honest evaluation; broker paper remains later, separate work. |
| 11 | [Glossary](glossary.md) | Start here | Plain names for the engine’s plan codes, workstreams, research safeguards, and paper-trading terms. |

## Suggested paths

For a five-minute overview, read **The trading engine**, **The daily cycle**, and **Roadmap**.

For implementation behavior, continue through **Data and time**, **Paper books and the league**,
and **AI agents**.

For research methodology, read **How research earns a verdict** and **The shared backtest core**.
For operating and recovery behavior, read **Evidence and reliability** and **Operations**.

<!-- sources: docs/site/index.md, docs/site/daily-cycle.md, docs/site/data.md, docs/site/paper-books.md, docs/site/ai-agents.md, docs/site/research-process.md, docs/site/backtest-engine.md, docs/site/evidence-and-reliability.md, docs/site/operations.md, docs/site/roadmap.md, docs/site/glossary.md -->

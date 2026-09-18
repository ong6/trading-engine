"""Documentation contracts for registered and published research evidence."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote

from engine import forward_review, xs_forward_review
from farm import experiment_runner
from farm.sweep import sweep
from farm.walkforward import protocol as walkforward_protocol
from server import (
    fundamentals_readiness,
    intraday_readiness,
    stock_readiness,
    walkforward_artifacts,
)
from sim.strategies.configs import CONFIGS

REPO_ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")


def test_current_docs_match_configured_league_and_replayable_counts():
    active_configs = [config for config in CONFIGS if config.get("active", True)]
    active_portfolios = len(active_configs) + 1  # discretionary paper book
    replayable = sum(
        walkforward_protocol.excluded_reason(config["id"], config["strategy"]) is None
        for config in active_configs
    )
    readme = " ".join((REPO_ROOT / "README.md").read_text().split())
    how = " ".join((REPO_ROOT / "docs" / "how-it-works.md").read_text().split())

    assert f"{active_portfolios} active paper portfolios" in readme
    assert f"{replayable} historically replayable rules" in readme
    assert f"{active_portfolios} active paper portfolios" in how
    assert f"{replayable} are historically replayable rules" in how


def test_docs_index_separates_live_authority_from_dated_snapshots():
    index = (REPO_ROOT / "docs" / "README.md").read_text()
    current, historical = index.split("## Historical audits and snapshots", 1)
    backlog = (REPO_ROOT / "docs" / "strategy-research-backlog.md").read_text()
    compact_backlog = " ".join(backlog.split())

    assert "`GET /meta` and the dashboard prospective-evidence cards" in current
    assert "dated narrative documents are snapshots" in current
    assert "document filename or top-level title marks a snapshot" in current
    assert "`miner_evidence` reconciles the four canonical producers" in current
    assert "`friday_postflight` interprets" in current
    assert "not `logs/friday-postflight.json` alone" in current
    assert "# Strategy research backlog\n" in backlog
    assert not backlog.startswith("# Strategy research backlog —")
    assert "Dated counts below are explicitly historical baseline snapshots" in compact_backlog
    assert "generated forward reports remain authoritative" in compact_backlog
    assert (
        "execution-capital-data-hardening-2026-09-06.md"
        not in current.split("## Design and specification", 1)[0]
    )
    assert "execution-capital-data-hardening-2026-09-06.md" in historical


def test_root_readme_separates_current_evidence_from_dated_review():
    readme = " ".join((REPO_ROOT / "README.md").read_text().split())

    assert "Current decision ledger: [`docs/strategy-research-backlog.md`]" in readme
    assert "Current runtime evidence comes from `GET /meta`" in readme
    assert "Dashboard prospective-evidence cards" in readme
    assert "and generated forward reports" in readme
    assert (
        "[`docs/review-2026-09-06.md`](docs/review-2026-09-06.md) is a detailed dated "
        "historical snapshot"
    ) in readme
    assert "Deterministic Sunday walk-forward re-validation" in readme
    assert "former autonomous model review is retired" in readme
    assert "inform only an explicit human review" in readme
    assert "feeds the Sunday review" not in readme


def test_current_research_backlog_documents_unattended_data_admission_path():
    backlog = (REPO_ROOT / "docs" / "strategy-research-backlog.md").read_text()
    compact_backlog = " ".join(backlog.split())

    assert "2026-09-08 pre-nightly baseline snapshot" in compact_backlog
    assert "not current runtime state" in compact_backlog
    assert "`GET /research/readiness` is authoritative for current coverage" in compact_backlog
    assert "naturally advances as unattended producers" in compact_backlog
    assert "`GET /meta` remains authoritative for current producer evidence" in compact_backlog
    assert "`e1_forward` object are authoritative for the current count" in compact_backlog
    assert "7/40 immutable OOS observations" not in compact_backlog
    assert "queues both intraday resolutions every weekday" in compact_backlog
    assert "at least 75% of the bars expected from the published NYSE schedule" in compact_backlog
    assert "zero usable breadth to unknown or closed dates" in compact_backlog
    assert "actual same-date ticker intersection" in compact_backlog
    assert "finite positive market cap and at least one finite valuation input" in compact_backlog
    assert "finite negative ratios remain valid" in compact_backlog
    assert "Only `ready` inputs can reach `READY_FOR_CHARTER`" in compact_backlog
    assert "malformed legacy schemas" in compact_backlog
    assert "Friday plan also queues fundamentals" in compact_backlog
    assert "That historical receipt was not reconstructed" in compact_backlog
    assert "does not lower any admission threshold" in compact_backlog
    assert "At the 2026-09-11 snapshot" in compact_backlog
    assert "stock selection had 40 of 756 qualifying shared dates" in compact_backlog
    assert "fundamentals had 8 of 156 qualifying snapshots" in compact_backlog
    assert "46 of 252 qualifying one-minute sessions" in compact_backlog
    assert "99 of 252 five-minute sessions" in compact_backlog
    assert "These are progress counters, not strategy results" in compact_backlog
    assert "another search over the current history would only spend trials" in compact_backlog


def test_current_research_backlog_separates_candidates_and_forbids_premature_work():
    backlog = " ".join(
        (REPO_ROOT / "docs" / "strategy-research-backlog.md").read_text().split()
    )

    assert "Live decision checkpoint — 2026-09-12 06:00 UTC" in backlog
    assert "The primary deployable-strategy candidate is" in backlog
    assert "Sector momentum is `ACCUMULATING` at 5/200 shared sessions" in backlog
    assert "E1 is `ACCUMULATING` at 7/40 observations" in backlog
    assert "Miner evidence is current at 4/4" in backlog
    assert "no new strategy run is currently admitted" in backlog
    assert "checked 3,968/4,093 names" in backlog
    assert "49 field disagreements (17 material)" in backlog
    assert "`price_verification` as `issues`, not clean" in backlog
    assert "supports a secondary-source anomaly" in backlog
    assert "05:15 UTC Friday postflight published" in backlog
    assert "scheduled 06:00 UTC sweep runner then exited cleanly" in backlog
    assert "no job enqueued" in backlog
    assert "`sweep_evidence.status = idle`" in backlog
    assert "Do not tune a frozen rule" in backlog
    assert "Source-transition checkpoint — 2026-09-13 02:17 UTC" in backlog
    assert "`walkforward_evidence.status = stale-source`" in backlog
    assert "were not reconstructed or manually relabelled" in backlog
    assert "`walkforward_evidence.status = current`" in backlog
    assert "Next admissible actions" in backlog
    assert "There is currently no evidence-authorized new strategy run" in backlog
    assert "source parity is provenance, not profit evidence" in backlog
    assert "earliest possible calendar-span clearance is around 2027-07-08" in backlog
    assert "no claim before roughly July 2029 at the earliest" in backlog
    assert "instead of relaxing the rule after seeing the outcome" in backlog


def test_entry_points_link_directly_to_next_admissible_actions():
    root_readme = (REPO_ROOT / "README.md").read_text()
    docs_readme = (REPO_ROOT / "docs" / "README.md").read_text()

    assert "docs/strategy-research-backlog.md#next-admissible-actions" in root_readme
    assert "strategy-research-backlog.md#next-admissible-actions" in docs_readme


def test_current_guides_document_the_completed_walkforward_source_transition():
    index = " ".join((REPO_ROOT / "docs" / "README.md").read_text().split())
    goal = " ".join((REPO_ROOT / "docs" / "live-readiness-goal.md").read_text().split())
    current_source = "2a45f846b7a4628661c4539adf71074377c529a450c90cb07cd4125aafed7d75"
    current_cohort = "b304ae92d54e27a8f3a3adaa77dcf5b77175f9be141e71dfa232f29c3b32aec2"

    assert current_source in index
    assert current_source in (
        REPO_ROOT / "docs" / "strategy-research-backlog.md"
    ).read_text()
    assert current_cohort in index
    assert "source-matching and current" in index
    assert "If the live source and published walk-forward cohort differ" in goal
    assert "let the scheduled revalidation restore a matching cohort" in goal
    assert "do not reconstruct evidence" in goal


def test_current_guide_documents_the_bounded_agent_proposal_ledger():
    how = " ".join((REPO_ROOT / "docs" / "how-it-works.md").read_text().split())

    assert "exact server-validated context payload" in how
    assert "GET /agent/proposals" in how
    assert "newest 100 records" in how
    assert "execution_authority = none" in how
    assert "retained context payload" in how
    assert "Context schema v10" in how
    assert "complete normalized record and recomputable hash" in how
    assert "agent_daily_price_observations" in how
    assert "baseline_snapshot" in how
    assert "GET /agent/data/daily-prices" in how
    assert "agent_corporate_action_observations" in how
    assert "GET /agent/data/corporate-actions" in how
    assert "agent_provider_responses" in how
    assert "agent_provider_source_observations" in how
    assert "exact-response source observations" in how
    assert "later_exact_value_corroboration" in how
    assert "GET /agent/data/provider-responses" in how
    assert "agent_independent_price_responses" in how
    assert "agent_independent_price_observations" in how
    assert "GET /agent/data/independent-price-evidence" in how
    assert "distinct corroborated observations" in how
    assert "additions and removals separately" in how
    assert "raw_retained = true" in how
    assert "usage_authority = shadow_context_only" in how
    assert "http://127.0.0.1:8317/v1/responses" in how
    assert "GPT-5.6-Sol:max" in how
    assert "no tools" in how
    assert "cannot fall through to another provider" in how
    assert "unversioned-catalog-alias" in how
    assert "server.agent_shadow_runner" in how
    assert ".agent-shadow.lock" in how
    assert "There are no automatic retries" in how
    assert "GET /agent/shadow/attempts" in how
    assert "unfinished older market-date window" in how
    assert "persistent user-systemd timer" in how
    assert "store/agent-shadow-control.json" in how
    assert "GET /agent/shadow/control" in how
    assert "GET /agent/attribution" in how
    assert "unavailable_no_isolated_paper_portfolio" in how
    assert "GET /agent/authority/readiness" in how
    assert "Schema v3" in how
    assert "review-packet gate now passes" in how
    assert "server.agent_fault_drills run" in how
    assert "GET /agent/fault-drills" in how
    assert "agent-shadow-state-machine-v1" in how
    assert "tools.initialize_agent_paper_book" in how
    assert "tools.migrate_agent_human_approval" in how
    assert "tools.migrate_agent_paper_authority_store" in how
    assert "tools.migrate_agent_release_review" in how
    assert "all twenty-eight cases" in how
    assert "broker_paper_authority_store.py" in how
    assert "broker_paper_consumption_store.py" in how
    assert "Enable automatic paper" in how
    assert "tools.adjudicate_agent_data_discrepancy" in how
    assert "agent_data_discrepancy_decisions" in how
    assert "record_only_separate_follow_up_required" in how
    assert "no cache writer, quarantine writer, order route, or" in how
    assert "broker_human_paper_review.py" in how
    assert "broker_human_paper_approval.py" in how
    assert "SHA-256 detects ordinary corruption but is not a" in how
    assert "approval_source = not_selected" in how
    assert "signer_policy = not_selected" in how
    assert "reconstructs the packet from the complete DuckDB evidence path" in how
    assert "rejects a forged evidence hash" in how
    assert "Packet schema v2" in how
    assert "independently validated signal close" in how
    assert "untrusted_model_rationale" in how
    assert "Raw context, prompts, model requests, and evidence-ID arrays are excluded" in how
    assert "tools.review_agent_paper_intent build" in how
    assert "tools.review_agent_paper_intent verify" in how
    assert "Both paths force DuckDB read-only" in how
    assert "transient user-systemd probe" in how
    assert "both later paper stages as ineligible" in how
    assert "default-disabled shadow control" in how
    assert "does not regenerate a consumed decision" in how
    assert "Hybrid remains absent from the timer and simulator" in how
    assert "Algorithm-only scheduling remains unchanged" in how
    assert "bounded `decision_features` section" in how
    assert "SPY/EFA/BIL over 252 sessions" in how
    assert "corporate-action fetch coverage" in how
    assert "first live manual invocation" in how


def test_current_guides_document_the_nasdaq_security_class_boundary():
    how = " ".join((REPO_ROOT / "docs" / "how-it-works.md").read_text().split())
    design = " ".join(
        (REPO_ROOT / "docs" / "design" / "trading-engine-design.md").read_text().split()
    )

    assert "treats Nasdaq's `ETF=Y` field as authoritative" in how
    assert "dedicated `.U` or terminal-`U` symbol" in how
    assert "ordinary operating-partnership units such as ET, MPLX, and PAA" in how
    assert "deactivated, never deleted, during the next normal universe refresh" in how
    assert "explicit preferred classes" in design
    assert "ordinary common partnership units remain eligible" in design


def test_dashboard_uses_monitor_owned_prospective_evidence_boundaries():
    dashboard = (
        REPO_ROOT / "ui" / "app" / "components" / "DashboardProspectiveEvidence.js"
    ).read_text()
    ui_guide = (REPO_ROOT / "ui" / "README.md").read_text()

    for field in (
        "minimum_shared_sessions",
        "minimum_paired_months",
        "target_observations",
        "eligible_after",
        "sample_end",
    ):
        assert field in dashboard
    assert "No candidate has established prospective positive excess return" in dashboard
    assert "cannot promote a strategy, allocate capital" in dashboard
    assert "monitor-owned observation targets and date boundaries" in ui_guide


def test_current_docs_do_not_promise_early_fundamentals_or_profit_readiness():
    current_docs = (
        REPO_ROOT / "docs" / "how-it-works.md",
        REPO_ROOT / "docs" / "design" / "trading-engine-design.md",
    )
    for path in current_docs:
        normalized = " ".join(path.read_text().split())
        assert "fundamentals" in normalized
        assert "1,095" in normalized
        assert "156" in normalized
        assert (
            "fundamentals → enables honest **value** strategies in ~6–12 months" not in normalized
        )
        assert "After 6–12 months this is real forward evidence" not in normalized


def test_current_docs_match_live_research_admission_thresholds():
    how = " ".join((REPO_ROOT / "docs" / "how-it-works.md").read_text().split())
    backlog = " ".join(
        (REPO_ROOT / "docs" / "strategy-research-backlog.md").read_text().split()
    )
    stock = (
        f"{stock_readiness.MIN_SHARED_DATES:,} shared universe/screen dates with at least "
        f"{stock_readiness.MIN_NAMES_PER_DATE:,} names over "
        f"{stock_readiness.MIN_CALENDAR_DAYS:,} days"
    )
    fundamentals = (
        f"{fundamentals_readiness.MIN_SNAPSHOTS:,} fundamentals snapshots with at least "
        f"{fundamentals_readiness.MIN_NAMES_PER_SNAPSHOT:,} names over "
        f"{fundamentals_readiness.MIN_CALENDAR_DAYS:,} days"
    )
    intraday = (
        f"{intraday_readiness.MIN_SESSIONS:,} sessions with at least "
        f"{intraday_readiness.MIN_TICKERS_PER_INTERVAL:,} tickers over "
        f"{intraday_readiness.MIN_CALENDAR_DAYS:,} days in each of the 1m and 5m archives"
    )
    for phrase in (stock, fundamentals, intraday):
        assert phrase in how

    assert (
        f"at least {stock_readiness.MIN_SHARED_DATES:,} qualifying stock dates spanning "
        f"{stock_readiness.MIN_CALENDAR_DAYS:,} calendar days"
    ) in backlog
    assert (
        f"{fundamentals_readiness.MIN_SNAPSHOTS:,} qualifying fundamentals snapshots spanning "
        f"{fundamentals_readiness.MIN_CALENDAR_DAYS:,} days"
    ) in backlog
    assert (
        f"{intraday_readiness.MIN_SESSIONS:,} qualifying sessions spanning "
        f"{intraday_readiness.MIN_CALENDAR_DAYS:,} days in both stored intraday resolutions"
    ) in backlog
    assert f"at least {stock_readiness.MIN_NAMES_PER_DATE:,} distinct names" in backlog
    assert f"at least {intraday_readiness.MIN_TICKERS_PER_INTERVAL:,} distinct tickers" in backlog
    assert (
        f"at least {intraday_readiness.MIN_SESSION_COVERAGE_FRACTION:.0%} of the bars"
        in backlog
    )


def test_completed_fixed_instrument_charters_match_published_rejections():
    studies = {
        "fixed_etf_rebalancing_premium.md": "fixed-etf-rebalancing-v1",
        "sell_in_may_spy.md": "sell-in-may-spy-v1",
        "turn_of_month_spy.md": "turn-of-month-spy-v1",
        "vix_term_spy_timing.md": "vix-term-spy-v1",
    }
    for charter_name, report_name in studies.items():
        charter = (REPO_ROOT / "docs" / "charters" / charter_name).read_text()
        result = json.loads(
            (
                REPO_ROOT
                / "data"
                / "reports"
                / "experiments"
                / report_name
                / "result.json"
            ).read_text()
        )

        assert "— completed research charter" in charter.splitlines()[0]
        assert "prospective research charter" not in charter.splitlines()[0]
        assert f"Charter ID: `{result['charter_id']}`" in charter
        assert result["decision"] == "REJECT-V1"
        assert result["paper_only"] is True
        assert result["automatic_action"] == "none"
        assert "REJECT-V1" in charter
        assert "not a paper book" in charter or "not approved for the paper league" in charter


def test_portfolio_backed_charter_lifecycle_matches_live_config_registry():
    configs = {config["id"]: config for config in CONFIGS}
    active_control = (
        REPO_ROOT / "docs" / "charters" / "xs_momentum_12_1.md"
    ).read_text()
    retired = (REPO_ROOT / "docs" / "charters" / "multi_asset_trend.md").read_text()
    withdrawn = (REPO_ROOT / "docs" / "charters" / "xs_reversal_1m.md").read_text()

    assert configs["xs_momentum_12_1"].get("active", True) is True
    assert "Status: **book — the control**" in active_control
    assert configs["multi_asset_trend"]["active"] is False
    assert "Status: **retired" in retired
    assert "xs_reversal_1m" not in configs
    assert "Status: **designed, withdrawn before registration**" in withdrawn


def test_documentation_index_links_every_owned_document():
    root = REPO_ROOT / "docs"
    index_path = root / "README.md"
    index = index_path.read_text()
    expected = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*.md")
        if path != index_path
    }
    linked = []
    for raw_target in MARKDOWN_LINK.findall(index):
        target = raw_target.strip()
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1]
        target = unquote(target.split("#", 1)[0])
        if not target:
            continue
        resolved = (root / target).resolve()
        try:
            relative = resolved.relative_to(root.resolve())
        except ValueError:
            continue
        if resolved.suffix == ".md":
            linked.append(relative.as_posix())

    missing = sorted(expected - set(linked))
    unexpected = sorted(set(linked) - expected)
    assert expected
    assert not missing, f"documents missing from docs/README.md: {missing}"
    assert not unexpected, f"unexpected internal docs links in docs/README.md: {unexpected}"


def test_report_root_guide_classifies_every_top_level_artifact():
    root = REPO_ROOT / "data" / "reports"
    guide = (root / "README.md").read_text()
    compact_guide = " ".join(guide.split())
    docs_index = (REPO_ROOT / "docs" / "README.md").read_text()
    entries = sorted(path.name for path in root.iterdir() if path.name != "README.md")
    missing = [name for name in entries if f"[`{name}" not in guide]

    assert entries
    assert not missing, f"top-level reports missing from data/reports/README.md: {missing}"
    assert all(
        not path.is_dir() or (path / "README.md").is_file()
        for path in root.iterdir()
    ), "every top-level report family must have its own README.md"
    assert "data/reports/README.md" in docs_index
    assert "strategy-research-backlog.md" in guide
    assert "`GET /meta`" in guide
    assert "not by itself evidence of a profitable strategy" in compact_guide
    assert "including retired portfolios" in compact_guide
    assert "not a current strategy ranking" in compact_guide


def test_forward_family_guide_lists_every_artifact_and_maturity_boundary():
    root = REPO_ROOT / "data" / "reports" / "forward"
    guide = (root / "README.md").read_text()
    compact_guide = " ".join(guide.split())
    artifacts = sorted(path.name for path in root.iterdir() if path.name != "README.md")

    assert artifacts
    assert all(f"[`{name}`]" in guide for name in artifacts)
    assert "machine-readable checkpoints validated by `GET /meta`" in compact_guide
    assert "full 12-month window" in compact_guide
    assert "at least 200 shared sessions" in compact_guide
    assert "frozen 2026-09-30 signal" in compact_guide
    assert "at least 48 paired complete months" in compact_guide
    assert "not that the candidate has established a profitable edge" in compact_guide
    assert "strategy-research-backlog.md" in guide


def test_walkforward_guide_separates_current_results_and_retained_snapshots():
    root = REPO_ROOT / "data" / "reports" / "walkforward"
    guide = (root / "GUIDE.md").read_text()
    generated_index = (root / "README.md").read_text()
    compact_guide = " ".join(guide.split())
    per_book_pages = sorted(
        path.name
        for path in root.glob("*.md")
        if path.name not in {"GUIDE.md", "README.md"} and not path.name.startswith("monthly-")
    )
    dated_stems = {path.stem for path in root.glob("monthly-*.*")}
    active_replayable = {
        config["id"]
        for config in CONFIGS
        if config.get("active", True)
        and walkforward_protocol.excluded_reason(config["id"], config["strategy"]) is None
    }
    current_pages = {f"{config_id}.md" for config_id in active_replayable}
    retained_pages = set(per_book_pages) - current_pages

    assert per_book_pages
    assert current_pages <= set(per_book_pages)
    assert all(f"]({name})" in generated_index for name in current_pages)
    assert retained_pages
    assert all(f"[`{name}`]({name})" in guide for name in retained_pages)
    assert all((root / "results" / f"{Path(name).stem}.json").is_file() for name in per_book_pages)
    assert dated_stems
    assert all(
        (root / f"{stem}.md").is_file() and (root / f"{stem}.json").is_file()
        for stem in dated_stems
    )
    assert "[`results/`](results/) is the moving canonical JSON result directory" in compact_guide
    assert "`monthly-*.md` and `monthly-*.json` are dated review snapshots" in compact_guide
    assert "[`migrations/`](migrations/) contains immutable before/after cohorts" in compact_guide
    assert "not scheduler inputs" in compact_guide
    assert "retained historical outputs, not members of the latest cohort" in compact_guide
    assert "unregistered legacy artifacts are ignored" in compact_guide
    assert "generated index still describes its `PASS`/`WATCH`/`REVIEW` triage" in compact_guide
    assert "model-driven review loop was retired on 2026-08-18" in compact_guide
    assert "Sunday now runs deterministic walk-forward revalidation only" in compact_guide
    assert "not a current operating instruction" in compact_guide
    assert "Changing the renderer requires an explicit evidence migration" in compact_guide
    assert "No layer in this directory is independent prospective evidence" in compact_guide
    assert "[`../forward/`](../forward/)" in guide


def test_backtest_guide_indexes_every_published_book_without_promoting_it():
    root = REPO_ROOT / "data" / "reports" / "backtests"
    guide = (root / "GUIDE.md").read_text()
    compact_guide = " ".join(guide.split())
    pages = sorted(
        path.name for path in root.glob("*.md") if path.name not in {"GUIDE.md", "README.md"}
    )
    result_books = {
        path.stem.rsplit("__", 1)[0] for path in (root / "results").glob("*.json")
    }

    assert pages
    assert all(f"[`{name}`]({name})" in guide for name in pages)
    assert result_books == {Path(name).stem for name in pages}
    assert "[`results/`](results/)" in guide
    assert "This entire cohort is `legacy_unstamped`" in compact_guide
    assert "cannot establish profitability or authorize a rerun" in compact_guide
    assert "`IN-SAMPLE-CONTEXT`" in compact_guide


def test_sweep_archive_guide_lists_every_legacy_grid_and_current_authority():
    root = REPO_ROOT / "data" / "reports" / "sweeps"
    guide = (root / "README.md").read_text()
    compact_guide = " ".join(guide.split())
    grids = sorted(path.name for path in root.iterdir() if path.is_dir())

    assert grids
    assert all(f"`{name}/`" in guide for name in grids)
    assert "strategy-research-backlog.md" in guide
    assert "supersedes any apparent next-step language" in compact_guide
    assert "not a queue of strategies awaiting promotion" in compact_guide
    assert "OPEN_RECURRING_GRIDS` is intentionally empty" in compact_guide
    assert sweep.OPEN_RECURRING_GRIDS == {}


def test_experiment_family_guide_classifies_every_report():
    root = REPO_ROOT / "data" / "reports" / "experiments"
    guide = (root / "README.md").read_text()
    study_dirs = sorted(path.name for path in root.iterdir() if path.is_dir())

    assert study_dirs
    assert all(f"[`{name}/`]" in guide for name in study_dirs)
    assert "e1-spy-monday-forward.md" in guide
    assert "exactly 40 eligible observations" in guide
    assert "Completed historical studies" in guide
    assert "strategy-research-backlog.md" in guide
    assert "live capital" in guide


def test_capital_sensitivity_guide_lists_every_snapshot_and_rejects_profit_claims():
    root = REPO_ROOT / "data" / "reports" / "capital-sensitivity"
    guide = " ".join((root / "README.md").read_text().split())
    strategies = sorted(path.name for path in root.iterdir() if path.is_dir())

    assert strategies
    assert all(f"[`{name}/5y/`]" in guide for name in strategies)
    assert "not whether a strategy has a reliable edge" in guide
    assert "does not establish positive excess over a proper control" in guide
    assert "XS report remains explicitly survivor-biased" in guide
    assert "strategy-research-backlog.md" in guide
    assert "live capital" in guide


def test_current_docs_pin_live_forward_runtime_contracts():
    how = (REPO_ROOT / "docs" / "how-it-works.md").read_text()
    xs_charter = (REPO_ROOT / "docs" / "charters" / "xs_momentum_12_1.md").read_text()
    backlog = (REPO_ROOT / "docs" / "strategy-research-backlog.md").read_text()

    for module, documents, artifact, nested in (
        (
            forward_review,
            (how, backlog),
            REPO_ROOT / "data" / "reports" / "forward" / "sector_momentum.json",
            True,
        ),
        (
            xs_forward_review,
            (how, xs_charter, backlog),
            REPO_ROOT / "data" / "reports" / "forward" / "xs_momentum_12_1.json",
            True,
        ),
        (
            experiment_runner,
            (how, backlog),
            REPO_ROOT / "data" / "reports" / "experiments" / "e1-spy-monday-forward.json",
            False,
        ),
    ):
        version = f"v{module.RUNTIME_CONTRACT_VERSION}"
        digest = module.EXPECTED_RUNTIME_CONTRACT_SHA256
        for text in documents:
            assert version in text
            assert digest in text
        payload = json.loads(artifact.read_text())
        runtime = payload["frozen_runtime"] if nested else payload
        assert runtime["runtime_contract_version"] == module.RUNTIME_CONTRACT_VERSION
        assert runtime["runtime_contract_sha256"] == digest


def test_current_research_docs_match_published_walkforward_cohort():
    results_dir = REPO_ROOT / "data" / "reports" / "walkforward" / "results"
    expected = {
        config["id"]
        for config in CONFIGS
        if config.get("active", True)
        and walkforward_protocol.excluded_reason(config["id"], config["strategy"]) is None
    }
    published = {}
    cohort_signatures = set()
    for path in sorted(results_dir.glob("*.json")):
        payload = json.loads(path.read_text())
        config_id = payload.get("config_id")
        if config_id not in expected:
            continue
        assert config_id not in published, f"duplicate walk-forward result for {config_id}"
        published[config_id] = payload
        _, signature = walkforward_artifacts.signature(payload)
        cohort_signatures.add(signature)

    assert set(published) == expected
    assert len(cohort_signatures) == 1, cohort_signatures
    cohort_sha256 = next(iter(cohort_signatures))
    source_hashes = {payload["source_sha256"] for payload in published.values()}
    assert len(source_hashes) == 1, source_hashes
    source_sha256 = next(iter(source_hashes))

    for path in (
        REPO_ROOT / "docs" / "README.md",
        REPO_ROOT / "docs" / "strategy-research-backlog.md",
    ):
        text = path.read_text()
        assert source_sha256 in text, path
        assert cohort_sha256 in text, path


def test_current_docs_disclose_mutable_walkforward_input_boundary():
    how = " ".join((REPO_ROOT / "docs" / "how-it-works.md").read_text().split())
    charter = " ".join((REPO_ROOT / "docs" / "charters" / "xs_reversal_1m.md").read_text().split())

    assert "not a byte-for-byte archive of the replay inputs" in how
    assert "Pinning an anchor fixes the fold dates" in how
    assert "tools/audit_walkforward_migration.py" in how
    assert "live `walkforward_evidence` validator recompute each snapshot SHA-256" in how
    assert "right shape cannot authorize snapshot drift" in how
    assert "reported as current evidence" in how
    assert "reject duplicate JSON object keys" in how
    assert "reject non-standard or non-finite JSON numbers" in how
    assert "structures deeper than the shared 100-level safety limit" in how
    assert "Operational JSON file reads are capped at 1 MiB" in how
    assert "Unregistered legacy result files are identified and ignored" in how
    assert "registered ten-fold plan" in how
    assert "each index 1–10 exactly once" in how
    assert "status: dropped" in how
    assert "not a profitable outcome" in how
    assert "reconstructs all ten calendar windows" in how
    assert "independently derives each book's `data_floor`" in how
    assert "requires the artifact to match" in how
    assert "Missing required history" in how
    assert "self-consistent but shifted dates" in how
    assert "must also equal the frozen live protocol" in how
    assert "uniformly altered cohort cannot redefine the experiment" in how
    assert "later weekday collection does not by itself invalidate" in how
    assert "must also equal a fresh aggregation" in how
    assert "producer's own summarizer" in how
    assert "edited headline metric" in how
    assert "arithmetically self-consistent" in how
    assert "train and validation equity must join" in how
    assert "does not contain the daily path needed to recompute them independently" in how
    assert "valid non-results only with an explicit reason" in how
    assert "Producer-owned assumptions are bound to live code" in how
    assert "`fill_model` must equal the simulator's current version" in how
    assert "`data_quality_class` must equal the strategy classifier" in how
    assert "uniformly mislabeled cohort" in how
    assert "Exact rerun reproducibility" in how
    assert "withdrew it before league registration" in charter
    assert "There is no portfolio row, queue job, or live record" in charter
    assert "the registration stands" not in charter

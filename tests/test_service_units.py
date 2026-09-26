"""Versioned user-service contracts for the local paper UI and API."""

import json
from pathlib import Path

from tools import install_automation

REPO_ROOT = Path(__file__).resolve().parents[1]


def _unit(relative: str) -> str:
    return (REPO_ROOT / relative).read_text()


def _assert_common_service_hardening(unit: str):
    for directive in (
        "PrivateTmp=true",
        "ProtectSystem=full",
        "ProtectControlGroups=true",
        "UMask=0077",
    ):
        assert directive in unit
    assert "ProtectKernelModules=" not in unit


def test_api_service_is_loopback_only_and_restart_safe():
    unit = _unit("server/trading-engine-api.service")
    assert "--host 127.0.0.1 --port 8000" in unit
    assert "Restart=on-failure" in unit
    assert "WantedBy=default.target" in unit
    assert "WorkingDirectory=%h/trading-engine" in unit
    # This API projects the installed user crontab. On this systemd 241 user
    # manager, each omitted directive implicitly sets the kernel no-new-privs
    # bit and prevents the setgid helper from reading its spool.
    for directive in (
        "NoNewPrivileges=",
        "ProtectKernelTunables=",
        "LockPersonality=",
        "RestrictRealtime=",
    ):
        assert directive not in unit
    _assert_common_service_hardening(unit)


def test_ui_service_is_production_loopback_and_depends_on_api():
    unit = _unit("ui/trading-engine-ui.service")
    package = json.loads(_unit("ui/package.json"))
    assert "Wants=trading-engine-api.service" in unit
    assert "ExecStartPre=%h/tools/node/bin/npm run build" in unit
    assert "npm run start -- --hostname 127.0.0.1 --port 3000" in unit
    assert "npm run dev" not in unit
    assert "Restart=on-failure" in unit
    assert "WantedBy=default.target" in unit
    assert package["scripts"]["build"] == "next build --webpack"
    for directive in (
        "NoNewPrivileges=true",
        "ProtectKernelTunables=true",
        "LockPersonality=true",
        "RestrictRealtime=true",
    ):
        assert directive in unit
    _assert_common_service_hardening(unit)


def test_persistent_header_fails_visibly_when_meta_api_is_unavailable():
    header = _unit("ui/app/components/Header.js")
    header_status = _unit("ui/app/components/HeaderStatus.js")
    operational = _unit("ui/app/components/HeaderOperationalStatus.js")
    contracts = _unit("ui/app/lib/meta-contracts.js")
    job_contracts = _unit("ui/app/lib/meta-job-contracts.js")
    server_api = _unit("ui/app/lib/server-api.js")
    assert "const data = res.ok && res.data ? res.data : {};" in header_status
    assert header_status.count("res.ok && res.data") == 1
    assert "const apiAlert = !res.ok" in operational
    assert 'res.busy ? "database busy"' in operational
    assert ': "unavailable"' in operational
    assert '<span className="research-fail">' in operational
    assert "<HeaderStatus res={res} />" in header
    assert "export function isMetaProjection(data)" in contracts
    assert '"weekly_walkforward"' in job_contracts
    assert "isMetaJobState(data)" in contracts
    assert "isMetaEvidence(data)" in contracts
    assert "isMetaExposure(data)" in contracts
    assert "isMetaForwardEvidence(data)" in contracts
    assert "isMetaProjection" in server_api
    assert 'validateApiResponse(await apiFetch("/meta"), "meta"' in server_api


def test_persistent_header_separates_verifier_driver_from_evidence_health():
    header = _unit("ui/app/components/HeaderOperationalStatus.js")
    assert '<span className="k">weekly verifier </span>' in header
    assert '<span className="k">price evidence </span>' in header
    assert 'priceVerification.status !== "current"' in header


def test_persistent_header_exposes_scheduler_health_and_entry_count():
    header = _unit("ui/app/components/HeaderOperationalStatus.js")
    status = _unit("ui/app/lib/header-status.js")
    assert '<span className="k">automation </span>' in header
    assert 'scheduler.status !== "ok"' in header
    assert "schedulerLabel(scheduler)" in header
    assert "scheduler.matched_entries" in status
    assert "scheduler.expected_entries" in status
    assert "scheduler.missing_drivers" in status
    assert "scheduler.duplicate_drivers" in status
    assert "scheduler.auxiliary_matched_entries" in status
    assert "scheduler.auxiliary_expected_entries" in status
    assert "scheduler.missing_auxiliary_entries" in status
    assert "scheduler.duplicate_auxiliary_entries" in status
    assert "scheduler.unlaunchable_auxiliary_entries" in status
    assert "scheduler.timezone_ok" in status
    assert "scheduler.unexecutable_drivers" in status
    assert "scheduler.unsafe_log_targets" in status
    assert "scheduler.log_directory_writable" in status
    assert "scheduler.cron_service_enabled" in status
    assert '<span className="k">git tracking </span>' in header
    assert 'sourceControl.status !== "current"' in header
    assert "sourceControl.ahead" in header
    assert "sourceControl.behind" in header


def test_daily_opportunity_publishes_canonical_evaluation_after_success():
    unit = _unit("server/trading-engine-daily-opportunity.service")
    runner = _unit("server/run_daily_opportunity.sh")
    assert "Type=exec" in unit and "Restart=on-failure" in unit
    assert "ExecStart=%h/trading-engine/server/run_daily_opportunity.sh" in unit
    assert "ExecStartPost=" not in unit
    assert "python -m server.daily_opportunity_runner" in runner
    assert "exec .venv/bin/python -m server.agent_evaluation_reporting" in runner
    _assert_common_service_hardening(unit)


def test_intraday_agents_validate_credentials_before_loading_them():
    runner = _unit("server/run_hourly_opportunity.sh")
    for name, variant in (("hourly", "hourly_market_watch_v5"),
                          ("four-hour", "four_hour_opportunity_review_v5")):
        unit = _unit(f"server/trading-engine-{name}-opportunity.service")
        assert "EnvironmentFile=" not in unit
        assert f"run_hourly_opportunity.sh {variant}" in unit
    assert runner.index("--preflight") < runner.index("--run-observer")
    assert "\nsource " not in runner and "read -r" not in runner


def test_tradingview_archive_timer_is_bounded_and_queue_owned():
    service = _unit("server/trading-engine-tradingview-history.service")
    timer = _unit("server/trading-engine-tradingview-history.timer")
    runner = _unit("server/run_tradingview_history_archive.sh")
    _assert_common_service_hardening(service)
    assert "TimeoutStartSec=4h" in service and "Nice=19" in service
    assert "03,07,11,15,19,23:40:00 UTC" in timer and "Persistent=true" in timer
    assert "--enqueue tradingview_history" in runner
    assert "--run --run-kind tradingview_history" in runner
    assert '"max_chunks":50' in runner and "official_quote_source" not in runner


def test_p15_scoring_unit_is_registered_but_not_autostarted():
    service = _unit("server/trading-engine-p15-scoring.service")
    timer = _unit("server/trading-engine-p15-scoring.timer")
    _assert_common_service_hardening(service)
    assert "server.p15_scoring_runner --run" in service
    assert "TimeoutStartSec=9h" in service
    assert "02:30:00 UTC" in timer and "Persistent=true" in timer
    assert "trading-engine-p15-scoring.timer" not in install_automation.AUTOSTART_UNITS


def test_p15_preopen_unit_is_registered_but_not_autostarted():
    service = _unit("server/trading-engine-p15-preopen.service")
    timer = _unit("server/trading-engine-p15-preopen.timer")
    _assert_common_service_hardening(service)
    assert "server.p15_preopen --run" in service
    assert "TimeoutStartSec=20min" in service
    assert "09:05:00 America/New_York" in timer and "Persistent=false" in timer
    assert "trading-engine-p15-preopen.timer" not in install_automation.AUTOSTART_UNITS


def test_p15_event_unit_is_intraday_shadow_and_not_autostarted():
    service = _unit("server/trading-engine-p15-events.service")
    timer = _unit("server/trading-engine-p15-events.timer")
    _assert_common_service_hardening(service)
    assert "farm.p15_event_runner --run" in service
    assert "TimeoutStartSec=14min" in service
    assert "09:35,50:00 America/New_York" in timer
    assert "10..15:05,20,35,50 America/New_York" in timer
    assert "Persistent=false" in timer
    assert "trading-engine-p15-events.timer" not in install_automation.AUTOSTART_UNITS


def test_league_ui_does_not_present_operational_rank_as_research_evidence():
    league = _unit("ui/app/league/page.js")
    standings = _unit("ui/app/components/LeagueStandings.js")
    dashboard = _unit("ui/app/components/DashboardLeagueSummary.js")

    assert "ordered by raw return since each book&apos;s" in league
    assert "vs SPY context" in standings
    assert "league.notice" in league
    assert "Operational league summary" in dashboard
    assert "not comparable\n            research evidence or a promotion signal" in dashboard


def test_league_ui_fetches_all_equity_series_in_one_request():
    league = _unit("ui/app/league/page.js")
    overview = _unit("ui/app/components/LeagueOverview.js")
    standings = _unit("ui/app/components/LeagueStandings.js")
    dashboard = _unit("ui/app/components/DashboardLeagueSummary.js")
    contracts = _unit("ui/app/lib/league-contracts.js")

    assert 'apiFetch("/league/equities")' in league
    assert "equity_by_portfolio" in league
    assert "encodeURIComponent(r.id)" not in league
    assert "rows.map((r) => apiFetch" not in league
    assert "const curvesAvailable = equitiesRes.ok" in league
    assert "validateApiResponse(" in league
    assert '"bulk-equity"' in league
    assert "isBulkEquityProjection(data, league)" in league
    assert "isRecord(data.equity_by_portfolio)" in contracts
    assert "isLeagueProjection" in league
    assert "entry.portfolio_id === portfolioId" in contracts
    assert "Number.isFinite(entry.equity)" in contracts
    assert "entry.date > priorDate" in contracts
    assert "portfolioIds.length !== expectedIds.length" in contracts
    assert "Object.prototype.hasOwnProperty.call(equityByPortfolio, id)" in contracts
    assert "data.portfolio_matching_count !== league?.matching_count" in contracts
    assert "entry.date <= asOf" in contracts
    assert ".filter((entry)" not in league
    assert "excluded from ranking" in overview
    assert "Ranking was calculated across the complete matching cohort" in overview
    assert "stale · {fmtDate(row.equity_as_of)}" in standings
    assert "equity curves are unavailable" in overview
    assert "<StateNotice res={equitiesRes} />" in overview
    assert '<span className="faint">unavailable</span>' in standings
    assert "<LeagueOverview" in league
    assert "<LeagueStandings" in league
    assert "apiFetch" not in overview
    assert "apiFetch" not in standings
    assert "validateApiResponse" not in overview
    assert "validateApiResponse" not in standings
    assert "currentLeagueRows" in dashboard
    assert "excluded from this summary" in dashboard


def test_positions_ui_discloses_bounded_order_history():
    orders = _unit("ui/app/components/PositionsOrders.js")
    read_models = _unit("server/order_read_models.py")

    assert "ORDERS_LIMIT = 500" in read_models
    assert "COUNT(*) OVER () AS _matching_count" in read_models
    assert '"matching_count": matching_count' in read_models
    assert '"truncated": matching_count > ORDERS_LIMIT' in read_models
    assert "ordersRes.data?.truncated === true" in orders
    assert "Showing newest ${fmtInt(orderLimit)} of ${fmtInt(" in orders
    assert "matching active-book orders." in orders


def test_positions_ui_discloses_bounded_position_list():
    positions = _unit("ui/app/components/PositionsOpenPositions.js")
    read_models = _unit("server/position_read_models.py")

    assert "POSITIONS_LIMIT = 500" in read_models
    assert "COUNT(*) OVER () AS _matching_count" in read_models
    assert '"matching_count": matching_count' in read_models
    assert '"truncated": matching_count > POSITIONS_LIMIT' in read_models
    assert "positionsRes.data?.truncated === true" in positions
    assert "Showing first ${fmtInt(positionLimit)} of ${fmtInt(" in positions
    assert "matching active-book positions, ordered by portfolio and ticker." in positions


def test_positions_ui_fails_visibly_on_malformed_success_payloads():
    positions = _unit("ui/app/positions/page.js")
    open_positions = _unit("ui/app/components/PositionsOpenPositions.js")
    orders = _unit("ui/app/components/PositionsOrders.js")
    contracts = _unit("ui/app/lib/response-contracts.js")
    operations = _unit("ui/app/lib/operations-contracts.js")
    position_contracts = _unit("ui/app/lib/positions-contracts.js")
    order_contracts = _unit("ui/app/lib/orders-contracts.js")
    order_read_models = _unit("server/order_read_models.py")
    position_read_models = _unit("server/position_read_models.py")

    assert "validateApiResponse(" in positions
    assert 'validateApiResponse(res, "positions"' in positions
    assert 'validateApiResponse(res, "orders"' in positions
    assert 'validateApiResponse(res, "league", isLeagueProjection)' in positions
    assert "isPositionsProjection(data, requestedPortfolio)" in positions
    assert "isOrdersProjection(data, requestedStatus)" in positions
    assert 'const DISC = "discretionary"' in positions
    assert 'const STATUSES = ["pending", "filled", "rejected", "cancelled"]' in positions
    assert "order.portfolio_id === DISC" in orders
    assert "...STATUSES.map" in positions
    assert "<PositionsOpenPositions" in positions
    assert "<PositionsOrders" in positions
    assert "apiFetch" not in open_positions
    assert "apiFetch" not in orders
    assert "validateApiResponse" not in open_positions
    assert "validateApiResponse" not in orders
    assert 'export { isPositionsProjection } from "./positions-contracts.js"' in operations
    assert 'export { isOrdersProjection } from "./orders-contracts.js"' in operations
    assert "data.portfolio !== (requestedPortfolio || null)" in position_contracts
    assert "Number.isFinite(row.avg_cost)" in position_contracts
    assert "Number.isFinite(row.market_value)" in position_contracts
    assert "nearlyEqual(row.market_value, row.qty * row.close)" in position_contracts
    assert "(row.close - row.avg_cost) / row.avg_cost" in position_contracts
    assert "(row.close - row.stop) / row.close" in position_contracts
    assert 'isBoundedCollection(data, "positions")' in position_contracts
    assert 'isBoundedCollection(data, "orders")' in order_contracts
    assert "SELECT p.*" not in position_read_models
    assert "p.qty, p.avg_cost" in position_read_models
    assert "SELECT o.*" not in order_read_models
    assert "SELECT matching.*" not in order_read_models
    assert "o.status, o.reject_reason" in order_read_models
    assert "hasExactOrderKeys(row)" in order_contracts
    assert "data.status !== (requestedStatus || null)" in order_contracts
    assert "ORDER_STATUSES.includes(row.status)" in order_contracts
    assert "terminalWithoutFill" in order_contracts
    assert "isNonEmptyString(row.reject_reason)" in order_contracts
    assert "isIsoDate(row.signal_date)" in order_contracts
    for domain_contracts in (position_contracts, order_contracts):
        assert "apiFetch" not in domain_contracts
        assert "validateApiResponse" not in domain_contracts
    assert "items.length === Math.min(count, limit)" in contracts
    assert "truncated === (count > limit)" in contracts
    assert "!leagueRes.ok ? <StateNotice res={leagueRes} /> : null" in open_positions


def test_journal_queries_only_fills_linked_to_visible_discretionary_tickets():
    read_models = _unit("server/journal_read_models.py")

    assert "SELECT t.*" not in read_models
    assert "t.playbook, t.emotion, t.notes, t.gates, t.status" in read_models
    assert "f.order_id IN ({placeholders})" in read_models
    assert "sorted(order_ids)" in read_models


def test_market_read_models_project_explicit_screen_columns():
    read_models = _unit("server/market_read_models.py")
    contracts = _unit("ui/app/lib/market-contracts.js")

    assert "SELECT * FROM screen_results" not in read_models
    assert "SCREEN_RESULT_COLUMNS" in read_models
    assert "hasExactScreenResultKeys(row)" in contracts
    assert '"ex-leveraged"' in contracts


def test_journal_ui_renders_and_discloses_bounded_histories():
    tickets = _unit("ui/app/components/JournalTickets.js")
    round_trips = _unit("ui/app/components/JournalRoundTrips.js")
    events = _unit("ui/app/components/JournalLeagueEvents.js")
    read_models = _unit("server/journal_read_models.py")

    assert "LEAGUE_EVENTS_LIMIT = 100" in read_models
    assert "DISCRETIONARY_TICKETS_LIMIT = 100" in read_models
    assert "ROUND_TRIPS_LIMIT = 100" in read_models
    assert '"league_events_matching_count": league_events_matching_count' in read_models
    assert (
        '"league_events_truncated": league_events_matching_count > LEAGUE_EVENTS_LIMIT'
        in read_models
    )
    assert "Recent league events" in events
    assert "discretionary tickets." in tickets
    assert "closed round-trips." in round_trips
    assert "Newest fills from active paper books; this is not a complete archive." in events
    assert "Showing newest ${fmtInt(limit)} of ${fmtInt(" in events


def test_journal_ui_fails_visibly_on_malformed_success_payloads():
    journal = _unit("ui/app/journal/page.js")
    sections = "".join(
        _unit(f"ui/app/components/{name}.js")
        for name in (
            "JournalCircuitBreaker",
            "JournalTickets",
            "JournalRoundTrips",
            "JournalLeagueEvents",
        )
    )
    operations = _unit("ui/app/lib/operations-contracts.js")
    journal_contracts = _unit("ui/app/lib/journal-contracts.js")

    assert 'validateApiResponse(res, "journal"' in journal
    assert "isJournalProjection" in journal
    assert 'export { isJournalProjection } from "./journal-contracts.js"' in operations
    assert '"tickets_matching_count"' in journal_contracts
    assert "validTicket(ticket)" in journal_contracts
    assert '"round_trips_matching_count"' in journal_contracts
    assert "validRoundTrip(roundTrip)" in journal_contracts
    assert '"league_events_matching_count"' in journal_contracts
    assert "validLeagueEvent(event)" in journal_contracts
    assert "validFill(fill, ticket)" in journal_contracts
    assert "fill.ticker === ticket.ticker" in journal_contracts
    assert "fill.side === ticket.side" in journal_contracts
    assert "validOrderLink" in journal_contracts
    assert 'ticket.status === "rejected"' in journal_contracts
    assert "hasExactKeys(ticket" in journal_contracts
    assert "hasExactKeys(fill, FILL_KEYS)" in journal_contracts
    assert '"invalid-entries"' in journal_contracts
    assert "apiFetch" not in journal_contracts
    assert "validateApiResponse" not in journal_contracts
    assert "if (!res.ok)" in journal
    assert "<StateNotice res={res} />" in journal
    for component in (
        "JournalCircuitBreaker",
        "JournalTickets",
        "JournalRoundTrips",
        "JournalLeagueEvents",
    ):
        assert f"<{component}" in journal
    assert "apiFetch" not in sections
    assert "validateApiResponse" not in sections


def test_dashboard_and_candidate_fail_visibly_on_malformed_success_payloads():
    dashboard = _unit("ui/app/page.js")
    screen = _unit("ui/app/components/DashboardScreen.js")
    candidate = _unit("ui/app/candidates/[ticker]/page.js")
    candidate_route = _unit("ui/app/lib/candidate-route.js")
    candidate_sections = "".join(
        _unit(f"ui/app/components/{name}.js")
        for name in ("CandidateSummary", "CandidateTemplateChecks", "CandidateTicketPanel")
    )
    api = _unit("ui/app/lib/api.js")
    primitives = _unit("ui/app/lib/response-contracts.js")
    core = _unit("ui/app/lib/meta-core-contracts.js")
    market = _unit("ui/app/lib/market-contracts.js")
    league = _unit("ui/app/lib/league-contracts.js")
    research = _unit("ui/app/lib/research-contracts.js")
    research_coverage = _unit("ui/app/lib/research-coverage-contracts.js")
    mutations = _unit("ui/app/lib/mutation-contracts.js")

    assert 'import { isRecord } from "./response-contracts.js"' in api
    assert "export function isRecord(value)" in primitives
    assert '"price_quarantines_matching_count"' in core
    assert "export function isLeagueProjection(data)" in league
    assert "row.current !== (row.equity_as_of === data.as_of)" in league
    assert 'data.ranking_basis !== "total_return_since_each_portfolio_inception"' in league
    assert "compareLeagueRows(rows[index - 1], row) > 0" in league
    assert "compareUnicodeCodePoints(left.id, right.id)" in league
    assert "row.current ? row.rank !== expectedRank : row.rank !== null" in league
    for label in ("screen", "league", "research-readiness"):
        assert f'"{label}"' in dashboard
    assert "DashboardProspectiveEvidence res={metaRes}" in dashboard
    assert "isScreenProjection(data) && data.results_page === expectedPage" in dashboard
    assert "apiFetch(`/screen/latest?page=${screenPage}`)" in dashboard
    assert "decodeCandidateSegment(ticker)" in candidate
    assert "if (tk === null) notFound()" in candidate
    assert "decodeURIComponent(segment)" in candidate_route
    assert "encodeURIComponent(ticker)" in candidate_route
    assert "Next screen page" in screen
    assert "Return to the last screen page" in screen
    assert "data.n_passing !== data.results_matching_count" in market
    assert "data.results_new_today !== data.results.filter" in market
    assert "data.results_offset !== (data.results_page - 1) * data.results_limit" in market
    assert "data.results_has_next !==" in market
    assert "data.results.every((row)" in market
    assert "const validRow = isScreenResult(row" in market
    assert "passingOnly: true" in market
    assert "export function isScreenResult(" in market
    assert "data.ticker !== expectedTicker" in market
    assert "bar.high >= Math.max(bar.open, bar.close, bar.low)" in market
    assert "quoteBar?.close === data.latest_close" in market
    assert "isScreenResult(data.screen, { ticker: expectedTicker })" in market
    assert 'data.purpose !== "candidate_admission_only"' in research
    assert "validDatedCoverage(stock" in research
    assert "validIntradayCoverage(data.families.intraday)" in research
    assert "export function validInputStatus(family)" in research_coverage
    assert "export function validDatedCoverage(family, fields)" in research_coverage
    assert "export function validIntradayCoverage(family)" in research_coverage
    assert "data.families[name].status === expectedStatuses[name]" in research
    assert "data.ready_families.length === expectedReady.length" in research
    assert "validateApiResponse(" in candidate
    assert '"candidate"' in candidate
    assert "isCandidateProjection(data, expectedTicker)" in candidate
    for component in ("CandidateSummary", "CandidateTemplateChecks", "CandidateTicketPanel"):
        assert f"<{component}" in candidate
    assert "apiFetch" not in candidate_sections
    assert "validateApiResponse" not in candidate_sections
    assert "data.n_bars !== data.bars.length" in market
    assert "export function isTicketContextProjection(data)" in mutations


def test_ui_transport_and_response_contracts_have_one_way_dependencies():
    api = _unit("ui/app/lib/api.js")
    primitives = _unit("ui/app/lib/response-contracts.js")
    market = _unit("ui/app/lib/market-contracts.js")
    league = _unit("ui/app/lib/league-contracts.js")
    meta = _unit("ui/app/lib/meta-contracts.js")
    meta_domains = "".join(
        _unit(f"ui/app/lib/{name}.js")
        for name in (
            "meta-contract-utils",
            "meta-core-contracts",
            "meta-job-contracts",
            "meta-automation-contracts",
            "meta-evidence-contracts",
            "meta-exposure-contracts",
            "meta-forward-contracts",
        )
    )
    research = _unit("ui/app/lib/research-contracts.js")
    research_coverage = _unit("ui/app/lib/research-coverage-contracts.js")
    mutations = _unit("ui/app/lib/mutation-contracts.js")
    dashboard = _unit("ui/app/page.js")
    candidate = _unit("ui/app/candidates/[ticker]/page.js")

    assert 'import { isRecord } from "./response-contracts.js"' in api
    for contracts in (
        primitives,
        market,
        league,
        meta,
        meta_domains,
        research,
        research_coverage,
        mutations,
    ):
        assert "./api" not in contracts
        assert "fetch(" not in contracts
        assert "validateApiResponse(" not in contracts
    assert "export function isScreenProjection(data)" in market
    assert "export function isMetaProjection(data)" in meta
    assert "isMetaCore(data)" in meta
    assert "isMetaAutomation(data)" in meta
    assert "export function isResearchReadinessProjection(data)" in research
    assert 'from "./research-coverage-contracts.js"' in research
    assert "export function isCandidateProjection(data, expectedTicker)" in market
    assert "export function isTicketContextProjection(data)" in mutations
    assert "isScreenProjection" not in primitives
    assert "isLeagueProjection" not in primitives
    assert "isMetaProjection" not in primitives
    assert "isResearchReadinessProjection" not in meta
    assert "isMetaProjection" not in research
    assert "function validDatedCoverage" not in dashboard
    assert "function validIntradayCoverage" not in dashboard
    assert "bar.high >=" not in candidate
    assert "data.experiment_max_pct >" not in candidate


def test_server_reads_bypass_proxy_and_meta_is_request_memoized():
    api = _unit("ui/app/lib/api.js")
    api_origin = _unit("ui/api-origin.mjs")
    next_config = _unit("ui/next.config.mjs")
    server_api = _unit("ui/app/lib/server-api.js")
    header = _unit("ui/app/components/Header.js")
    header_statuses = "".join(
        _unit(f"ui/app/components/{name}.js")
        for name in (
            "HeaderStatus",
            "HeaderOperationalStatus",
            "HeaderResearchStatus",
        )
    )
    dashboard = _unit("ui/app/page.js")

    assert '"http://127.0.0.1:8000"' in api_origin
    assert "UI_INTERNAL_API_ORIGIN" in api_origin
    assert 'from "../../api-origin.mjs"' in api
    assert 'from "./api-origin.mjs"' in next_config
    assert "`${apiOrigin}/:path*`" in next_config
    assert "UI_INTERNAL_ORIGIN" not in api
    assert 'import "server-only"' in server_api
    assert "export const getMeta = cache(async () =>" in server_api
    assert 'validateApiResponse(await apiFetch("/meta"), "meta"' in server_api
    assert "await getMeta()" in header
    assert "getMeta" not in header_statuses
    assert "getMeta()," in dashboard
    assert 'apiFetch("/meta")' not in header
    assert 'apiFetch("/meta")' not in dashboard


def test_ui_proxy_enforces_the_shared_loopback_host_policy():
    proxy = _unit("ui/proxy.js")
    host_policy = _unit("ui/host-policy.mjs")

    assert 'from "./host-policy.mjs"' in proxy
    assert 'isAllowedUiHost(request.headers.get("host"))' in proxy
    assert 'new NextResponse("Invalid host header", { status: 400 })' in proxy
    assert '"127.0.0.1"' in host_policy
    assert '"localhost"' in host_policy
    assert "ALLOWED_UI_HOSTNAMES.has" in host_policy


def test_api_errors_are_always_safe_to_render_as_text():
    api = _unit("ui/app/lib/api.js")

    assert "export const API_ERROR_MAX_CHARS = 4_096" in api
    assert "export const API_VALIDATION_ERROR_MAX_ITEMS = 16" in api
    assert "export const API_RESPONSE_MAX_BYTES = 1_048_576" in api
    assert "function boundedErrorText(value)" in api
    assert 'typeof value !== "string"' in api
    assert 'value.replace(/[\\p{C}\\p{Z}\\s]+/gu, " ").trim()' in api
    assert ".slice(0, API_VALIDATION_ERROR_MAX_ITEMS)" in api
    assert 'const suffix = "additional validation errors omitted"' in api
    assert "Array.isArray(detail)" in api
    assert "boundedErrorText(item.msg)" in api
    assert 'boundedErrorText(normalizedSegments.join("."))' in api
    assert "error: apiError(data, res.status)" in api
    assert 'error: boundedErrorText(e?.message) || "network error"' in api
    assert "async function boundedResponseText(response)" in api
    assert "function declaredResponseTooLarge(value)" in api
    assert "BigInt(" not in api
    assert "bytesRead > API_RESPONSE_MAX_BYTES" in api
    assert "await reader.cancel()" in api
    assert "error: API_RESPONSE_TOO_LARGE" in api


def test_ticket_sizing_hint_never_silently_uses_hard_coded_equity():
    ticket = _unit("ui/app/components/TicketForm.js")
    trade_fields = _unit("ui/app/components/TicketTradeFields.js")
    ticket_panel = _unit("ui/app/components/CandidateTicketPanel.js")
    candidate = _unit("ui/app/candidates/[ticker]/page.js")
    mutations = _unit("ui/app/lib/mutation-contracts.js")

    assert "DEFAULT_EQUITY" not in ticket
    assert "apiFetch" not in ticket
    assert 'apiFetch("/tickets/context")' in candidate
    assert 'context?.status === "inactive"' in ticket
    assert "context.risk_pct" in ticket
    assert "isSizingContext(context, latestCloseDate)" in ticket
    assert 'context.portfolio_id === "discretionary"' in mutations
    assert "context.equity_source === expectedSource" in mutations
    assert "context.as_of === latestCloseDate" in mutations
    assert "candidate has no real quote on the operational market date" in ticket
    assert "latestCloseDate={data.latest_close_date}" in candidate
    assert 'active: "current_discretionary_equity"' in mutations
    assert '"not-created": "configured_initial_cash"' in mutations
    assert "Sizing suggestion unavailable" in trade_fields
    assert "server risk gates use current equity" in trade_fields
    assert "Number.isFinite(context.equity)" in mutations
    assert "suggestedTicketQty(entry, stop, equity, riskPct)" in ticket
    assert "fmtMoney(equity)" in trade_fields
    assert "current discretionary equity" in ticket
    assert 'validateApiResponse(res, "ticket-context"' in candidate
    assert "isTicketContextProjection" in candidate
    assert 'data.portfolio_id !== "discretionary"' in mutations
    assert '"active", "not-created", "inactive", "unavailable"' in mutations
    assert "data.experiment_max_pct > data.risk_pct" in mutations
    assert "!contextRes.ok ? <StateNotice res={contextRes} /> : null" in ticket_panel


def test_ticket_form_mirrors_server_text_limits():
    contract = _unit("server/ticket_contract.py")
    journal_fields = _unit("ui/app/components/TicketJournalFields.js")

    for name, value in (
        ("PLAYBOOK_MAX_CHARS", 128),
        ("NOTES_MAX_CHARS", 4_096),
        ("OVERRIDE_REASON_MAX_CHARS", 512),
    ):
        literal = f"{value:_}"
        assert f"{name} = {literal}" in contract
        assert f"{name} = {literal}" in journal_fields
        assert f"maxLength={{{name}}}" in journal_fields


def test_mutation_clients_validate_success_payloads_before_claiming_success():
    ticket = _unit("ui/app/components/TicketForm.js")
    ticket_children = "".join(
        _unit(f"ui/app/components/{name}.js")
        for name in ("TicketTradeFields", "TicketJournalFields", "TicketOutcome")
    )
    cancel = _unit("ui/app/components/CancelButton.js")
    review = _unit("ui/app/components/ReviewDoneButton.js")
    mutations = _unit("ui/app/lib/mutation-contracts.js")

    assert 'validateApiResponse(res, "ticket"' in ticket
    assert 'apiPost("/tickets", body)' in ticket
    assert "apiPost" not in ticket_children
    assert "validateApiResponse" not in ticket_children
    assert "isTicketMutationProjection" in ticket
    assert 'data.status === "submitted"' in mutations
    assert "isPositiveInteger(data.order_id)" in mutations
    assert 'data.status === "rejected"' in mutations
    assert "data.order_id === null" in mutations
    assert "!isPositiveInteger(data.ticket_id)" in mutations
    assert "!isIsoDate(data.signal_date)" in mutations
    assert "data.gates.length === 0" in mutations
    assert "isRiskGateResult(gate)" in mutations
    assert "hasExactKeys(gate, RISK_GATE_KEYS)" in mutations
    assert "hasExactKeys(data, TICKET_MUTATION_KEYS)" in mutations
    assert "hasExactKeys(data, TICKET_CANCELLATION_KEYS)" in mutations
    assert "hasExactKeys(data, REVIEW_COMPLETION_KEYS)" in mutations
    assert "isNonEmptyString(reason)" in mutations
    assert "MAX_REASON_CHARS" in mutations
    assert "data.reasons.length === 0" in mutations
    assert "data.reasons.length > 0" in mutations
    assert '"ticket cancellation"' in cancel
    assert "isTicketCancellationProjection(data, ticketId)" in cancel
    assert "data.ticket_id === ticketId" in mutations
    assert "isPositiveInteger(data.order_id)" in mutations
    assert 'data.status === "cancelled"' in mutations
    assert '"review completion"' in review
    assert "isReviewCompletionProjection" in review
    assert "data.ok === true" in mutations
    assert 'data.kind === "circuit_breaker"' in mutations
    assert "isIsoTimestamp(data.ts)" in mutations
    assert "isNonEmptyString(data.detail)" in mutations

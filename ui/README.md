# Trading-engine paper dashboard

This Next.js application is the local dashboard for the paper-trading engine.
It binds to `127.0.0.1:3000` and proxies `/api/*` to the FastAPI service on
`127.0.0.1:8000`. It is not authenticated and must not be exposed directly to
the network.

Browser requests use that same-origin proxy. Server-rendered components call
the loopback API directly; duplicate `/meta` reads within one render are
request-memoized, but no operational response is cached across page requests.
Set `UI_INTERNAL_API_ORIGIN` only when an isolated local API uses a different
port from `http://127.0.0.1:8000`. The validated origin configures both
server-rendered requests and the browser `/api/*` proxy; it must be an explicit
`http://127.0.0.1:PORT` origin with no credentials, path, query, or fragment.
Invalid or non-loopback values fail the build/start configuration.
Root `proxy.js` rejects every request whose Host hostname is not exactly `127.0.0.1` or
`localhost` (with a valid optional port) before rendering or forwarding `/api`. The API
independently enforces the same loopback-hostname boundary. Keep both checks if proxy behavior changes: they are
the DNS-rebinding boundary for these unauthenticated local services, not authentication.

Successful API payloads are checked before rendering by pure contracts in `app/lib/`:
`response-contracts.js` provides shared primitives; `market-contracts.js`,
`league-contracts.js`, `meta-contracts.js`, and `research-contracts.js` own their endpoint domains;
`operations-contracts.js` is the stable public facade for operational reads;
`positions-contracts.js`, `orders-contracts.js`, and `journal-contracts.js` own those three
response domains; and
`mutation-contracts.js` covers ticket/review responses, context, and sizing. Header status labels
are isolated in `header-status.js`. Run their dependency-free Node test suite with `npm test`;
use `npm run build` for the full production compilation check.

`meta-contracts.js` is the public `/meta` composition contract. Its pure domain validators are
split into `meta-core-contracts.js`, `meta-job-contracts.js`,
`meta-automation-contracts.js`, `meta-evidence-contracts.js`,
`meta-exposure-contracts.js`, and `meta-forward-contracts.js`, with shared predicates in
`meta-contract-utils.js`. Consumers import only `isMetaProjection` from the public facade.

`research-contracts.js` owns the aggregate `/research/readiness` response and derived family
statuses. Shared input-schema, dated-coverage, and intraday-coverage checks live in
`research-coverage-contracts.js`; both modules are pure and the dashboard imports only the
aggregate projection.

`operations-contracts.js` likewise preserves the public imports used by pages and tests while
delegating to the pure domain validators in `positions-contracts.js`, `orders-contracts.js`, and
`journal-contracts.js`. Those modules validate admitted response shapes only: fetching and
`validateApiResponse` remain at the route boundary.

`app/page.js` owns dashboard request fan-out and response-contract admission only. Its four
server-rendered sections live in `app/components/DashboardLeagueSummary.js`,
`DashboardProspectiveEvidence.js`, `DashboardResearchReadiness.js`, and `DashboardScreen.js`.
Keep endpoint validation in the page boundary and display-only transformations in those section
owners, so a malformed successful response still fails visibly before any section renders it.
The persistent header follows the same ownership rule: `Header.js` owns the `/meta` fetch, MOCK
banner, and navigation; `HeaderStatus.js` admits the validated result; and
`HeaderOperationalStatus.js` plus `HeaderResearchStatus.js` own the ordered status projections.
For discretionary tickets, `TicketForm.js` retains all client state, sizing-context decisions,
request construction, response validation, and submission effects. `TicketTradeFields.js`,
`TicketJournalFields.js`, and `TicketOutcome.js` are presentation-only children and must not call
the API or claim success from an unvalidated response.
`app/positions/page.js` owns position/order request fan-out, query-bound response validation, and
filter-option derivation. `PositionsOpenPositions.js` and `PositionsOrders.js` render the two
independent read-only sections; they receive admitted response objects and must not call or
validate API endpoints themselves. The cancellation control remains a separate mutation client.
`app/journal/page.js` owns journal response admission and the top-level fail-visible boundary.
`JournalCircuitBreaker.js`, `JournalTickets.js`, `JournalRoundTrips.js`, and
`JournalLeagueEvents.js` own its four ordered presentation sections without fetching or validating
API responses. The circuit-breaker section delegates its write to the existing validated
`ReviewDoneButton.js` mutation client.
`app/league/page.js` owns league/equity request fan-out, cross-response validation, and the
top-level fail-visible/empty boundary. `LeagueOverview.js` renders curve availability, table/curve
truncation, staleness, and current operating context; `LeagueStandings.js` renders the table and derives
sparkline values from already-admitted bulk equity rows. Neither presentation component fetches or
validates an endpoint.
`app/candidates/[ticker]/page.js` owns candidate/context request fan-out, ticker-bound response
validation, and candidate-not-found handling. `app/lib/candidate-route.js` safely decodes incoming
route segments, enforces the API's nonblank 32-character ticker boundary, and percent-encodes every
data-derived candidate link. Blank or oversized decoded segments become a normal 404. Malformed
UTF-8 percent sequences are rejected by Next before page code runs and can still produce its bare
500 response; no in-app link emits those sequences. `CandidateSummary.js`,
`CandidateTemplateChecks.js`, and `CandidateTicketPanel.js` render already-admitted data without
fetching or validating endpoints; the ticket panel delegates interactive state and mutation to
`TicketForm.js`.

## Persistent service

The production UI is supervised by the versioned user unit
`trading-engine-ui.service`. With user lingering enabled, it survives an SSH or
Codex disconnect and starts after reboot:

```bash
install -Dm644 ui/trading-engine-ui.service \
  ~/.config/systemd/user/trading-engine-ui.service
systemctl --user daemon-reload
systemctl --user enable --now trading-engine-ui.service
systemctl --user status trading-engine-ui.service --no-pager
```

The unit runs `npm run build` before each start and serves the resulting
production build with `npm run start`. The build script intentionally selects
Webpack: this Debian 10 host cannot load Next.js 16.3.4's native SWC binary, and
Turbopack does not support Next's WASM fallback. Do not remove `--webpack` until
the deployment host has a compatible glibc. Logs append to `logs/ui.log` in the
repository root. Restart after source changes with:

```bash
systemctl --user restart trading-engine-ui.service
```

## Development mode

For an interactive hot-reload session, stop the managed service first so both
processes do not compete for port 3000:

```bash
systemctl --user stop trading-engine-ui.service
ui/run_ui.sh
```

Restore the persistent production service afterward with
`systemctl --user start trading-engine-ui.service`.

Access the dashboard through an SSH tunnel:

```bash
ssh -L 3000:127.0.0.1:3000 <you>@<host>
```

Then open <http://localhost:3000>. The dashboard and API are paper-only; no
broker or live-capital integration is configured. The persistent header shows scheduler
continuity as `automation <status> (<production matched>/<expected> · postflight <matched>/<expected>)`
and highlights a stopped or boot-disabled cron daemon, non-UTC host timezone, missing/duplicate
production or auxiliary postflight entry, non-executable driver, or unwritable log directory. It
also catches a missing/unexecutable postflight Python or unreadable verifier module, and shows each
forward monitor's validated
runtime-contract version alongside its status; the full scheduler diagnostics and contract hashes
are available from `GET /meta` for operational auditing. These checks are read-only and never
repair cron or alter paper state.
After the first Saturday observation window, a failed, stale, malformed, or missing Friday
postflight receipt is also surfaced in this header. `not-yet-run`, a live 15-minute grace window,
and a current receipt remain neutral.

The adjacent `git tracking` field is also read-only and network-free. `local-only` means nightly
generated-data commits remain on this machine; `current` means only that `HEAD` matches the cached
tracking ref, not that the remote was contacted successfully.

The dashboard's **Prospective strategy evidence** strip is the concise answer to “do we have a
working strategy yet?” It reads the three fail-closed frozen monitors from `GET /meta`, including
their monitor-owned observation targets and date boundaries. `ACCUMULATING` or `WAITING` means the
answer is still no: none of these cards can promote a book, allocate capital, or authorize live
trading.

```bash
curl -fsS http://127.0.0.1:8000/meta
```

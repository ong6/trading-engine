# Security

The engine holds no credentials, connects to no broker and moves no money. It
fetches public market data and writes to a local DuckDB file. The API and UI are
designed to bind to loopback only; do not expose ports 8000 or 3000 directly to
an intranet or the public internet. Use the documented SSH tunnel for access.
Operational API failures expose stable status and reason codes, not raw exception
messages that may contain filesystem or database details. Full tracebacks remain in
the owner-only service journal for local diagnosis.
Persisted discretionary risk-gate corruption is likewise represented by a closed
`gates_error` code in `GET /journal`; the API does not return the malformed source
text or parser diagnostics, and admits only the public `name`, `status`, and `detail`
fields from valid stored gate entries.
Read-model queries name their public columns rather than exposing whole source-table rows, and
browser contracts reject unexpected order, screen, or stored-gate fields. Schema growth therefore
does not silently expand these loopback API responses.
Discretionary ticket text fields are length-bounded before database initialization, risk
evaluation, or audit persistence; the UI mirrors those limits but is not the enforcement boundary.
Read-route identifiers are bounded before database access as well: candidate tickers use the same
32-character ceiling, ticker/portfolio identifiers must be nonblank, portfolio identifiers are
capped at 128 characters, and ticket
cancellation IDs must be positive. In particular, an empty `portfolio` query cannot silently
become an unfiltered positions request.
Every paper-state mutation requires an explicit `application/json` content type before a write
connection opens. The browser client already sends JSON; rejecting form, text, multipart, and
missing media types prevents a cross-origin HTML form from reaching the unauthenticated loopback
mutation handlers. This is a local-browser safeguard, not a substitute for keeping both services
bound to loopback.
Both HTTP layers also reject any `Host` header whose hostname is not exactly `127.0.0.1` or
`localhost`; an optional port must be valid. The UI applies this check before page
rendering or `/api` proxying, and the API applies it before route or database handling. This
defends the unauthenticated local services against DNS-rebinding requests; it is not authentication
and must not be relaxed to admit external hostnames when exposing either service through another
host or proxy.

If you find something that leaks data off the box, executes untrusted input, or
lets a discretionary ticket bypass a risk gate, open a private security advisory
on GitHub rather than a public issue.

"""M3 — local mock-trading backend (FastAPI on 127.0.0.1:8000).

Serves the discretionary paper-trading dashboard: league standings, screen
results, candidate detail, positions, orders, journal, and — the point of M3 —
discretionary trade *tickets* whose risk gates (rules.md) are enforced
server-side before a ticket ever becomes a pending sim_orders row.

MOCK system: no broker, no auth, no secrets. Binds loopback only. Reads
prices/screen_results/sim_* read-only per request; writes only disc_tickets,
audit_log, review_markers, sim_orders (pending intents), and the single
'discretionary' portfolios row. The existing nightly league day-step fills those
pending orders at the next open — this server never fills or moves the league.
"""

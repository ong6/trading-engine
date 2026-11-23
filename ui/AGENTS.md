# ui/ — agent notes

**Frozen**: keep the dashboard building and its tests passing; add no features; do not design for
mobile. Change it only for a reproduced defect or an API contract change that forces it.

- Pages live in `app/`; each page owns its fetches and validates every response with the pure
  contracts in `app/lib/*-contracts.js` (`meta-contracts.js` is the `/meta` facade,
  `operations-contracts.js` the facade for positions, orders and journal). Components render
  admitted data only and never call the API.
- `proxy.js` and the API both reject non-loopback Host headers (the DNS-rebinding boundary); keep
  both. `UI_INTERNAL_API_ORIGIN` may only name an explicit `http://127.0.0.1:PORT`.
- Check with `npm test` and `npm run build`. Human setup and service notes: [`README.md`](README.md).

<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

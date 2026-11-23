# Paper dashboard

The local Next.js dashboard for the paper-trading engine. It binds to `127.0.0.1:3000` and
proxies `/api/*` to the API on `127.0.0.1:8000`. It has no authentication and must never be exposed
to the network. The dashboard is frozen: it is maintained, not extended, and is not designed for
mobile.

## Setup

Install the root Python environment first (`uv sync --extra dev --frozen`), then with Node.js 20.9+:

```bash
cd ui
npm ci
npm test
npm run build
```

Start `server/run_server.sh` from the repository root, then
`npm run start -- --hostname 127.0.0.1 --port 3000` from `ui/`. Reads need a populated local store
or a published snapshot; a missing or busy store shows as unavailable, never as invented data.

## Service

`trading-engine-ui.service` (installed by `tools.install_automation`) builds and serves the
production build and logs to `logs/ui.log`. The build uses Webpack because the host cannot load
the native SWC binary. For hot reload, stop the service and run `ui/run_ui.sh`.

## Access

```bash
ssh -L 3000:127.0.0.1:3000 <you>@<host>
```

Then open <http://localhost:3000>. The header's status row mirrors `GET /meta`; the prospective
evidence strip answers "is there a working strategy yet?" and none of its cards can promote a book
or authorize trading.

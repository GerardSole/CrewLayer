# CrewLayer Dashboard

React 18 + Vite + TypeScript + Tailwind CSS v3 + shadcn/ui dashboard for the CrewLayer backend.

## Stack

- **React 18** with React Router v6
- **Vite 5** (dev server + bundler)
- **TypeScript** strict mode
- **Tailwind CSS v3** — dark mode by default (class strategy)
- **shadcn/ui** components (slate theme)
- **@tanstack/react-query** for server state
- **recharts** for charts
- **axios** for HTTP
- **sonner** for toast notifications

## Development

```bash
cd dashboard
npm install
npm run dev          # http://localhost:5173
```

The dev server proxies `/v1/*` and `/health` to `http://localhost:8000` so you need the backend running locally.

## Build

```bash
npm run build        # outputs to dashboard/dist/
```

The build is served by FastAPI at `/dashboard/` (see `main.py`).

## Production (Docker)

The `Dockerfile` has a two-stage build:
1. Node 20-alpine builds the dashboard
2. Python 3.12-slim runs the API and serves `dashboard/dist/` at `/dashboard/`

```bash
docker compose up --build
# Dashboard: http://localhost:8000/dashboard/
# API:       http://localhost:8000/v1/
```

## Structure

```
src/
├── api/           # axios calls — one file per domain
├── components/
│   ├── shared/    # Layout, Sidebar, Header, EmptyState, ErrorBoundary
│   └── ui/        # shadcn/ui components
├── hooks/         # React Query hooks
├── lib/           # utils, constants, formatters
├── pages/         # one directory per route
│   ├── Login/
│   ├── Overview/
│   ├── Agents/
│   ├── Memory/
│   ├── Actions/
│   ├── Evaluations/
│   ├── Prompts/
│   ├── Blackboard/
│   ├── Webhooks/
│   ├── AuditLog/
│   └── Settings/
├── types/         # TypeScript interfaces mirroring the API
├── App.tsx
├── main.tsx
└── router.tsx
```

## Auth

Credentials (base URL + API key) are stored in `localStorage`. The login page validates the API key against `GET /v1/api-keys` before storing. A 401 response anywhere in the app clears credentials and redirects to `/login`.

## Adding shadcn components

```bash
npx shadcn@latest add <component-name>
```

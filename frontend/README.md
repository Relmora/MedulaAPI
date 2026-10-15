# MedulaAPI frontend

React, TypeScript, and Vite. Use Node.js 24 and npm.

## Setup

From `frontend/`:

```bash
npm ci
```

If `.env.local` does not already exist:

```bash
cp .env.example .env.local
```

The local configuration is:

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8000
```

This is public browser configuration. Never put database credentials, private API keys, or other secrets in `VITE_` variables.

## Run

Start the backend using the [backend guide](../backend/README.md), then run:

```bash
npm run dev
```

Open the URL printed by Vite, normally http://localhost:5173. The page calls the backend health endpoint and displays its connection status. It does not yet test database access or implement document workflows.

If Vite selects a different port, update `CORS_ALLOWED_ORIGINS` in `backend/.env` to include the actual frontend origin. Restart FastAPI after that change. Restart Vite after changing `.env.local`.

## Checks

```bash
npm run lint
npm run build
```

`build` runs TypeScript checking and generates the production assets. The API URL is included at build time; configure it for the target environment before building. Do not commit `dist/` or `node_modules/`.

## Troubleshooting

- **Request goes to `/undefined/health`:** place `.env.local` beside `package.json`, set `VITE_API_BASE_URL`, and restart Vite.
- **Backend unavailable:** open http://127.0.0.1:8000/health and check whether FastAPI is running.
- **Browser CORS error:** match the frontend's scheme, hostname, and port in backend settings. `localhost` and `127.0.0.1` are different origins.

Automated browser/component tests are still pending; lint and build checks are not substitutes for them.

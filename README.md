# MedulaAPI

Independent knowledge-platform project. Current implementation: a React frontend and FastAPI health endpoint. Document ingestion, knowledge graphs, authentication, and MCP are planned, not implemented.

## Local development

Prerequisites: Node.js 24 with npm, Git, and uv. uv manages backend Python 3.12.

Backend, in one terminal:

```bash
cd backend
uv sync --locked
uv run uvicorn backend.main:app --reload
```

Frontend, in another terminal from the repository root:

```bash
cd frontend
npm ci
cp .env.example .env.local
npm run dev
```

Copy the example only when `.env.local` does not already exist. Open http://localhost:5173 while the backend runs at http://127.0.0.1:8000. If Vite chooses another port, update the backend allowed origin before testing. Restart Vite after changing environment variables. VITE-prefixed variables are public browser configuration, never secrets.

## Checks before a pull request

From `backend/`:

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest -q
```

From `frontend/`:

```bash
npm run lint
npm run build
```

The frontend build includes TypeScript checking. GitHub Actions runs these checks on pushes and pull requests. Frontend browser/component automation and database setup are still pending.

Commit dependency lockfiles and `.env.example`; keep virtual environments, installed dependencies, and local environment files out of Git.

License selection is pending; no open-source license grant is made by this README.

# MedulaAPI

An independent knowledge-platform project under development.

Currently implemented: React frontend, FastAPI health endpoint, environment-based CORS configuration, a PostgreSQL connection factory, and baseline quality checks. Authentication, projects/deployments, ingestion, knowledge graphs, retrieval, MCP, and Alembic migrations are not implemented yet.

## Development stack

| Component | Tool |
| --- | --- |
| Frontend | React, TypeScript, Vite; Node.js 24 and npm |
| Backend | FastAPI, Python 3.12 managed by uv |
| Database | Native local PostgreSQL 18; SQLAlchemy and Psycopg |
| Planned migrations | Alembic |

Git is required. Both developers use separate local PostgreSQL databases; Docker is not required. Keep the same PostgreSQL major version across machines. An activated Python virtual environment is optional when using `uv run`.

## First-time setup

1. Clone the repository and enter it:

   ```bash
   git clone https://github.com/Relmora/MedulaAPI.git
   cd MedulaAPI
   ```

   GitHub access is required while the repository is private.

2. Follow the [backend setup guide](backend/README.md) to prepare your local database, install dependencies, configure your private `.env`, and verify the database connection.
3. Follow the [frontend setup guide](frontend/README.md) to install dependencies and configure `.env.local`.
4. Start both processes in separate terminals.

Backend terminal, from the repository root:

```bash
cd backend
uv run uvicorn backend.main:app --reload
```

Frontend terminal, from the repository root:

```bash
cd frontend
npm run dev
```

Open http://localhost:5173. The page should display **Backend connected**. API health is at http://127.0.0.1:8000/health and API documentation is at http://127.0.0.1:8000/docs. The health endpoint checks the API process, not PostgreSQL; use the backend guide's separate connection check to verify the database.

## Checks before pushing

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

The frontend build includes TypeScript checking. GitHub Actions runs the configured quality checks on pushes and pull requests. These checks do not exercise a live PostgreSQL server or browser end-to-end flow.

## Working as a team

Each developer keeps their own database, role password, and development data. Share source code, dependency lockfiles, setup instructions, and eventually Alembic migrations through Git—not database directories or credentials. After pulling dependency changes, run `uv sync --locked` in `backend/` and `npm ci` in `frontend/`.

Commit `uv.lock`, `package-lock.json`, and `.env.example` files. Never commit `.env`, `.env.local`, `.venv/`, or `node_modules/`. Backend credentials belong only in the backend's private environment. Browser-visible `VITE_` settings must never contain secrets.

License selection is pending; no open-source license grant is made by this README.

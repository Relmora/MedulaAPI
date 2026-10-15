# MedulaAPI backend

Requires uv. The project uses Python 3.12; uv can install it independently of your system Python.

From this directory:

```bash
uv sync --locked
uv run uvicorn backend.main:app --reload
```

Health endpoint: http://127.0.0.1:8000/health
Interactive API documentation: http://127.0.0.1:8000/docs

## Quality checks

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest -q
```

To format Python files, run `uv run ruff format .`.
Tests use an in-process API client; no running server or database is required.
CORS tests check browser access headers, not authentication. The health endpoint is public.

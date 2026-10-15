# MedulaAPI backend

Run commands below from `backend/` unless otherwise specified. Settings load `.env` relative to the working directory, so start backend commands here.

## Prerequisites

- uv, which manages this project's Python 3.12 environment.
- A running native PostgreSQL 18 server, with an administrative connection available for initial setup.
- A SQL client such as pgAdmin or `psql`.

Use your existing PostgreSQL installation. If using Postgres.app, start the server there; if using Homebrew, start its service. Do not start two servers on the same port. pgAdmin is a client: opening it is not proof that it started the server.

The current development connection uses `::1` (IPv6 localhost), port `5432`. Change these values in your private `.env` if your installation differs.

## Prepare your own development database

Skip creation if you already created and verified these objects. Each teammate performs setup independently on their own machine.

Using an administrative connection in pgAdmin:

1. Under **Login/Group Roles**, create `medula_app` with a private password and **Can login** enabled. Leave superuser, role creation, and database creation privileges disabled.
2. Create a database named exactly `MedullaAPI` if it does not exist.
3. Open the Query Tool connected to **MedullaAPI** as your administrator and execute:

```sql
GRANT CONNECT ON DATABASE "MedullaAPI" TO medula_app;
GRANT USAGE, CREATE ON SCHEMA public TO medula_app;
```

The database is spelled `MedullaAPI`; the repository is `MedulaAPI`. Database names in the connection settings must match exactly. Schema grants apply to the database you are connected to.

These permissions support local development and future migrations. They are not the final production permission model; migration and runtime access will be separated before production. No application tables are created by this setup.

Verify a new connection as `medula_app`, not the administrator:

```bash
psql -h ::1 -p 5432 -U medula_app -d MedullaAPI -W
```

If `psql` is not on PATH but Homebrew `libpq` is installed, use:

```bash
"$(brew --prefix libpq)/bin/psql" -h ::1 -p 5432 -U medula_app -d MedullaAPI -W
```

Enter your password at the prompt, then run:

```sql
SELECT
    current_user,
    current_database(),
    has_schema_privilege(current_user, 'public', 'USAGE') AS can_use_schema,
    has_schema_privilege(current_user, 'public', 'CREATE') AS can_create_tables;
```

Expect `medula_app`, `MedullaAPI`, and two true values. Exit `psql` with `\q`.

## Install and configure

```bash
uv sync --locked
```

If `.env` does not already exist, copy the template:

```bash
cp .env.example .env
```

Edit your private `.env` to contain the following settings, with each key appearing once:

```dotenv
CORS_ALLOWED_ORIGINS=["http://localhost:5173"]
DB_HOST=::1
DB_PORT=5432
DB_NAME=MedullaAPI
DB_USER=medula_app
DB_PASSWORD='YOUR_LOCAL_ROLE_PASSWORD'
```

Replace the password placeholder locally; do not commit or share it. Choose dotenv quoting/escaping appropriate to your password if it contains quotes. The Python connection factory uses `URL.create`, so the password is supplied as its original value, not URL-encoded text. Real environment variables override values from `.env`.

The settings loader rejects unexpected `.env` keys. `DB_PASSWORD` must be nonempty when constructing a database engine. The health endpoint does not construct one.

## Verify Python-to-database connectivity

This read-only check creates no tables and prints no password:

```bash
uv run python - <<'PYTHON'
from sqlalchemy import text

from backend.config import Settings
from backend.database import create_database_engine

engine = create_database_engine(Settings())
try:
    with engine.connect() as connection:
        database, user = connection.execute(
            text("SELECT current_database(), current_user")
        ).one()
        print(f"Connected to database: {database}")
        print(f"Connected as user: {user}")
finally:
    engine.dispose()
PYTHON
```

Expected database: `MedullaAPI`; user: `medula_app`.

## Run the API

```bash
uv run uvicorn backend.main:app --reload
```

Health: http://127.0.0.1:8000/health

Interactive documentation: http://127.0.0.1:8000/docs

Restart after editing `.env`. CORS origins must match the browser's exact scheme, hostname, and port. CORS is a browser access policy, not authentication.

## Quality checks

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest -q
```

To format Python files: `uv run ruff format .`.

Existing tests do not require a running PostgreSQL server; the connectivity check above is separate. Current health CORS tests expect `http://localhost:5173` to be permitted. Alembic and application table migrations will be added in R1; there is no migration command to run yet.

## Troubleshooting

- **Connection refused:** confirm the existing server is running and `.env` has its actual host/port.
- **Password authentication failed:** verify the password belongs to `medula_app`, not your administrator.
- **Database does not exist:** check the exact `MedullaAPI` spelling and the server you connected to.
- **Missing DB_PASSWORD:** run from `backend/` and set a nonempty password in its `.env`.
- **Permission denied for schema:** run the schema grants as an administrator connected to `MedullaAPI`, then reconnect as `medula_app`.

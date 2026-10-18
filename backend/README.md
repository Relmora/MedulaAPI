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

Existing tests do not require a running PostgreSQL server; the connectivity check above is separate. Current health CORS tests expect `http://localhost:5173` to be permitted. Alembic is configured below; migration commands are run by the user.

## Troubleshooting

- **Connection refused:** confirm the existing server is running and `.env` has its actual host/port.
- **Password authentication failed:** verify the password belongs to `medula_app`, not your administrator.
- **Database does not exist:** check the exact `MedullaAPI` spelling and the server you connected to.
- **Missing DB_PASSWORD:** run from `backend/` and set a nonempty password in its `.env`.
- **Permission denied for schema:** run the schema grants as an administrator connected to `MedullaAPI`, then reconnect as `medula_app`.

## Authentication foundation (step 1)

`src/backend/models/` defines users and browser login sessions. These are
schema definitions only: no auth endpoints or database tables are created yet.
One user can have multiple sessions. Each session stores a refresh-token hash,
an absolute expiry, and an optional revocation timestamp. Access JWTs will
reference the session ID; protected requests will check session/account status.
Usernames will be normalized to lowercase by the account/login service.

The user runs all migration commands. Do not use `create_all` to bypass migrations.
Refresh rotation and replay/concurrency handling are not implemented yet.

## Database migrations (step 2)

Alembic tracks schema changes as versioned Python files. `alembic/env.py` loads
`Base.metadata` and uses the same Settings/connection factory as the application.
Credentials stay in your private environment; no database URL is stored in
`alembic.ini`. Run from `backend/` so Settings reads the intended `.env`.
The application does not run migrations on startup.

The user runs every migration command. To generate the initial revision against
your existing development database:

```bash
uv run --locked alembic revision --autogenerate -m "create users and auth sessions"
```

This connects to PostgreSQL to inspect the schema and writes a candidate Python
revision under `alembic/versions/`; it does not apply the proposed table changes.
Review that file before proceeding. Expect creation of `users`, `auth_sessions`,
the user foreign key, unique constraints, check constraints, and the session
user-ID index. Investigate unexpected drops or unrelated changes. Autogenerate
is not a substitute for reviewing schema changes, particularly CHECK constraints
and any future renames or data transformations.

After review, apply and verify:

```bash
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic check
```

`upgrade` changes the database and records the revision in `alembic_version`.
`current` reports the applied revision. `check` detects supported schema
differences that would produce another autogenerated revision; it is not a
complete proof of schema correctness. Commit the reviewed revision with the
models. Other developers apply that same revision rather than generating it again.

No initial revision has been generated or applied as part of setup. Production
migration access must be separated from the runtime account before release.

## Password hashing (step 3)

`backend.auth.passwords` provides Argon2id hashing, verification, and detection
of hashes that need updated parameters. Only the encoded hash belongs in
`users.password_hash`. The library generates a fresh salt for every hash and
includes the salt and parameters in the encoded result; no separate salt column
is needed. Password input is preserved exactly, including whitespace and Unicode.
The helper rejects empty passwords and input above 1024 UTF-8 bytes without
truncation. This resource bound is not the account password-strength policy.

The explicit RFC 9106 low-memory profile uses 64 MiB per hashing operation.
Benchmark deployment concurrency and bound password-check work before exposing
login publicly. These synchronous helpers must not block an async event loop.
The login service must still implement rate limits, missing-user timing handling,
account status checks, and generic authentication failures. After successful
verification, it can rehash older credentials and persist the new hash.

No registration/login endpoint or session token issuance exists yet. This step
does not change the database schema and requires no migration.

## Account creation (step 4)

Set `REGISTRATION_ENABLED=true` in your private `.env` and restart the API to
allow `POST /auth/register`. It defaults to false. Submit JSON with `username`
and `password`; success returns HTTP 201 with only `id`, `username`, and
`created_at`. Registration now also creates a session and sets login cookies (see step 5).
Usernames are trimmed/lowercased and limited to 3-64 ASCII letters, digits,
underscores, dots and hyphens. Passwords are 15-128 characters, preserved exactly.
Duplicate normalized usernames return 409; this intentionally exposes username
availability. Invalid requests return 422 without echoing input/passwords.

Before public deployment, add shared abuse/rate limits, request-size limits,
and compromised-password screening. The registration switch alone is not an
abuse defense. Login/session endpoints are the next step. No schema migration
is required. Tests use an isolated in-memory SQLite database; PostgreSQL
integration and concurrent-registration verification remain release checks.

## Central logging and errors

Application modules use `from backend.logging import get_logger`, followed by
`logger = get_logger(__name__)`. Standard `debug`, `info`, `warning`, `error`, and
`exception` methods work. Set `LOG_LEVEL=INFO` (default) or `DEBUG` in `.env`.
Logs are JSON lines on stdout for collection by the deployment platform.

```python
logger.info("Account created", extra={"event": "auth.account_created"})
```

Use static messages. Never interpolate passwords, tokens, request bodies, SQL,
or exception strings into messages. The formatter permits only selected extra
fields and cannot redact arbitrary secrets deliberately placed in message text.
Exception logging includes type and stack locations, but omits exception values,
source lines and locals. Request logs include method, route template, status,
duration and a server-generated request ID; no headers, raw URLs or bodies.
Request IDs propagate into synchronous endpoint logs and return in X-Request-ID.
CORS exposes that header to the configured frontend. CORS preflight responses
are handled by CORS middleware before reaching application request logging.

Raise an expected public error using:

```python
from backend.errors import AppError
raise AppError("USERNAME_UNAVAILABLE", "Username is unavailable.", 409)
```

Errors now use `{"error": {"code": "...", "message": "...", "request_id": "..."}}`.
Validation errors additionally include safe locations/types, without raw input.
This replaces the earlier `detail` response format. Unknown failures return a
generic 500; expected errors retain their status. HTTP authentication headers
are preserved. Streaming failures after headers have been sent cannot replace
the response and are logged and re-raised.

Use `uv run uvicorn backend.main:app --reload --no-access-log` locally to avoid
Uvicorn's duplicate raw-URL access logs. This config owns the `backend` logger
namespace; Uvicorn lifecycle and third-party logs retain their own configuration.
Review server/proxy log policy separately for production. No database migration
is needed for logging or error handling.

## Login and session issuance (step 5)

`POST /auth/register` creates the user and session atomically, then sets cookies.
`POST /auth/login` accepts username/password and creates a session for an existing
active user. `GET /auth/me` returns the authenticated user after validating JWT
claims, stored session status/expiry, and account status. Database failures fail
closed. Tokens never appear in JSON responses or application logs.

Configure a cryptographically random `AUTH_SIGNING_KEY` of at least 32 bytes in
your private environment. For localhost HTTP only, set `AUTH_COOKIE_SECURE=false`;
production HTTPS must use true (the default). Access JWTs expire in 15 minutes;
sessions and random refresh credentials expire after 7 days. The database stores
only a SHA-256 verifier of the high-entropy refresh credential. Access cookies
use Path=/; refresh cookies use Path=/auth. Both are HttpOnly, SameSite=Lax,
host-only cookies. CORS permits credentialed requests from configured origins;
React must use `credentials: "include"`. Use the same hostname consistently.

Signup/login require JSON. Browser Origin is checked against explicit
AUTH_ALLOWED_ORIGINS and cross-site fetches are rejected; do not broaden these
origins with wildcards or derive trust from the Host header. Non-browser clients
may omit Origin. Future cookie-authenticated write endpoints must apply CSRF
protection as well.

Refresh rotation and logout endpoints are NOT implemented in this step. After
15 minutes, sign in again until refresh is implemented. No migration is needed.
Shared rate limits, compromised-password screening, PostgreSQL concurrency tests,
and deployment load testing remain required before production release.

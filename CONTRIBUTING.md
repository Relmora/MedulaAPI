# Contributing to MedulaAPI

## Setup

Follow README.md and the frontend/backend setup guides.

Each developer uses their own local database and credentials.
Never commit real passwords, `.env`, or `.env.local` files.

## Work on a branch

Start from the latest main branch with a clean working tree:

```bash
git switch main
git pull --ff-only origin main
git switch -c feat/short-description
```

Use a descriptive branch name:
- `feat/...` for features
- `fix/...` for fixes
- `docs/...` for documentation
- `test/...` for tests

Coordinate ownership before editing the same feature or files.

## Verify changes

From backend/:

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest -q
```

From frontend/:

```bash
npm run lint
npm test
npm run build
```

Run the checks relevant to your changes. All required CI checks
must pass before merging.

## Open a pull request

Push your branch and open a pull request targeting main.

Explain:
- What changed and why.
- How you verified it.
- Any configuration, dependency, or database implications.

Keep pull requests focused. Request review from your teammate
and resolve feedback before merging.

## Dependencies and database changes

Commit updated lockfiles when dependencies change.

Never share database directories or credentials through Git.
Once Alembic is introduced, database schema changes must include
reviewed migrations. Coordinate concurrent schema changes.

## Secrets and security

Do not include credentials or sensitive data in code, screenshots,
logs, issues, or pull requests.

Report suspected security vulnerabilities privately to the repository
maintainers rather than opening a public issue.
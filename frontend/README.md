# MedulaAPI frontend

React, TypeScript, Vite, shadcn/ui (Base UI / Nova), Axios, TanStack Query,
and React Router. Use Node.js 24 and npm.

## Setup

From frontend/:

```bash
npm ci
npm run dev
```

Set the public API address in .env.local:

```dotenv
VITE_API_BASE_URL=http://localhost:8000
```

Open http://localhost:5173. Use the same hostname for frontend and API:
do not mix localhost and 127.0.0.1. Restart Vite after changing .env.local.
Do not put credentials or private tokens in VITE_ variables.

Start PostgreSQL and FastAPI using the backend guide. The backend needs its
signing key, database, and developer-run migrations configured. Local HTTP needs
AUTH_COOKIE_SECURE=false; production HTTPS needs secure cookies. Registration
is disabled unless the backend operator enables REGISTRATION_ENABLED.
CORS_ALLOWED_ORIGINS and AUTH_ALLOWED_ORIGINS must include the exact frontend
origin, including its port.

## Structure

```text
src/
  components/ui/               shadcn components only
  services/
    http.ts                    Axios instances, errors, shared pagination type
    auth.ts                    auth endpoints and bounded session refresh
    workspace.ts               workspace API functions
    knowledge-base.ts          knowledge-base API functions
  providers/query-client.ts    TanStack Query setup and expired-session handling
  layouts/authenticated-layout.tsx
  login/
    login.tsx
    components/login-form.tsx
  workspace/
    workspace.tsx
    workspace-detail.tsx
    components/workspace-form.tsx
  knowledge-base/
    knowledge-base.tsx
    components/knowledge-base-list.tsx
    components/knowledge-base-form.tsx
  App.tsx                      React Router routes
  main.tsx                     QueryClientProvider and HashRouter
```

Keep endpoint URLs and Axios calls in services. Screens read data with useQuery
and perform writes with useMutation. Mutations update detail caches and
invalidate affected lists. Query keys include workspace IDs to separate results.
Custom UI components belong to their feature, not components/ui.

The cn package supplies shadcn's class helper directly; there is no src/lib folder.
Use the built-in shadcn styles and add only necessary layout classes.

## Authentication and navigation

Axios sends HttpOnly cookies using withCredentials. No tokens are stored in
localStorage or sessionStorage. The protected Axios instance refreshes once on
401 and shares an in-flight refresh across requests in this client. Requests are
not retried on arbitrary failures. Different browser tabs do not coordinate
refresh rotation.

Expired sessions return to login; signing in/out clears private query data.
React Router uses hash URLs so bookmarks and back/forward work on static hosts
without server rewrite configuration. Reads pass TanStack Query's AbortSignal
to Axios. Pending mutations disable submission and failed writes retain input.

The UI supports login/registration/logout, workspace list/create/rename, and
knowledge-base list/create/view/rename. Knowledge-base routes require the
issue #5 backend migration. Upload, sharing, deletion, and transfer remain out of scope.

## Checks

```bash
npm run lint
npm run build
```

Frontend automated tests and their dependencies have been removed as requested;
they will be added later. Frontend CI runs lint and the TypeScript/production build.
Backend tests are unchanged.

Manual verification: sign in, create a workspace and knowledge base, rename it,
return to its list, reload, then sign out. Verify errors and expired sessions too.
A browser check using a temporary API fixture does not verify real PostgreSQL
persistence or authorization; run the complete flow against the real backend
before treating issue #5 as complete.

Do not commit .env.local, dist/, or node_modules/.

# Running with Docker

This is the "real deployment" way to run the whole stack: a real
Postgres database instead of a SQLite file, the frontend built and
served as static files instead of Vite's dev server, and the backend
running with production-mode safety checks turned on.

For day-to-day development, don't use this — plain `uvicorn main:app
--reload` (backend) + `npm run dev` (frontend) is faster to iterate
with, since Docker requires a rebuild to pick up code changes and
Vite/uvicorn's `--reload` don't.

## Prerequisites

Docker and Docker Compose (Docker Desktop includes both). Nothing else
— no local Python, Node, or Postgres install needed for this path.

## Run it

```bash
docker compose up --build
```

First run will take a few minutes (pulling base images, installing
dependencies, building the frontend). Once it's up:

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- Postgres: exposed inside the Docker network only, not on your host —
  connect to it directly with `docker compose exec db psql -U
  delivery_sync` if you need to inspect it.

Stop everything with `Ctrl+C`, or `docker compose down` to also remove
the containers (the `postgres_data` volume — your actual data —
survives a `down` and is only removed with `docker compose down -v`).

## What's different from local (non-Docker) development

| | Local dev | Docker |
|---|---|---|
| Database | SQLite file | Real Postgres |
| Frontend | Vite dev server, hot reload | Built static files via nginx |
| Backend | `--reload`, `ENVIRONMENT` unset | No reload, `ENVIRONMENT=production` |
| `/docs` API explorer | On | Off (see main.py) |
| CORS | Wide open | Locked to `http://localhost:3000` |
| JWT signing key | Insecure dev fallback (with a warning) | Must be set, or the container won't start |

None of this is Docker-specific behavior — it's all driven by the
`ENVIRONMENT` and `DATABASE_URL` environment variables, which
docker-compose.yml just happens to set for you. You could set the same
variables and get the same behavior running the backend directly with
`uvicorn`, no Docker involved at all.

## Turning on real integrations

Every optional integration this project supports (SMTP email, Twilio
SMS/WhatsApp, Razorpay payments, VAPID push, Google Maps geocoding)
works the same way in Docker as it does locally: set the relevant
environment variables (see `backend/.env.example` for the full list),
either directly in `docker-compose.yml`'s `environment:` block or in a
`.env` file in the same folder as `docker-compose.yml` — Docker Compose
reads that automatically and it's the easiest way to keep secrets out
of the compose file itself.

## Changing the backend URL the frontend talks to

The frontend's `VITE_API_BASE_URL` is baked in at BUILD time (a Vite
thing, not a Docker thing — see `frontend/Dockerfile`'s comments).
Changing it means rebuilding the frontend image, not just restarting
the container:

```bash
docker compose up --build frontend
```

## Deploying for real (not just running locally)

This compose file is meant to be run on one machine for local
testing/demoing — it isn't a production deployment on its own (no
HTTPS termination, no real secrets management, Postgres data lives in
a local Docker volume with no backup strategy). For an actual public
deployment, the same Dockerfiles work as-is on any container platform
(Fly.io, Render, Railway, ECS, etc.) — you'd point `DATABASE_URL` at a
managed Postgres instance instead of the `db` service here, put a real
domain + HTTPS in front of both containers, and set real values for
`JWT_SECRET_KEY` / `ALLOWED_ORIGINS` / `FRONTEND_URL` through whatever
secrets mechanism that platform provides.

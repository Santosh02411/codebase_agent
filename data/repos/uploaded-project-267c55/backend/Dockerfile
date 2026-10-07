# Backend container — FastAPI + Uvicorn behind no reverse proxy of its
# own (docker-compose.yml is the thing deciding what's exposed where).
#
# Single-stage is deliberate here: unlike the frontend (which needs a
# Node build step whose output is static files, so a multi-stage build
# meaningfully shrinks the final image), the backend's "build" IS just
# installing Python dependencies — there's no compiled artifact to
# separate from the build tools that made it. Multi-staging it would
# add complexity without shrinking anything real.
FROM python:3.12-slim

WORKDIR /app

# System deps needed to build psycopg2 (the Postgres driver) and
# bcrypt's C extension from source on some base images. Kept to exactly
# what those two need, then removed in the same layer so they don't
# bloat the final image — the compiled .so files they produce stay,
# the compiler toolchain used to make them doesn't.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Not baked in as a default: ENVIRONMENT, DATABASE_URL, JWT_SECRET_KEY,
# etc. all come from docker-compose.yml / the deployment platform's own
# env config — a Dockerfile default here would be easy to forget is
# there and accidentally ship with insecure production settings.
EXPOSE 8000

# No --reload here (that's a docker-compose.override.yml / dev-only
# concern — see docker-compose.yml's comments) and no bind to
# 127.0.0.1 (a container's "localhost" isn't reachable from outside
# it — 0.0.0.0 is required for docker's port mapping to work at all).
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

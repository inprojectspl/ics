#!/bin/sh
# Backend entrypoint:
#   1. Wait for Postgres (compose `depends_on: service_healthy` already
#      handles this in normal flow, but the loop is cheap insurance for
#      bare `docker run` and external Postgres deployments).
#   2. Apply Alembic migrations to head. Idempotent, a no-op if already
#      current.
#   3. Exec the configured CMD (uvicorn).
#
# Set `ICS_SKIP_MIGRATIONS=1` to disable auto-migration (useful if you
# want a separate one-shot migration container in a Kubernetes deploy).

set -e

if [ -z "$ICS_SKIP_MIGRATIONS" ]; then
  echo "[entrypoint] alembic upgrade head"
  alembic upgrade head
else
  echo "[entrypoint] ICS_SKIP_MIGRATIONS is set, skipping migrations"
fi

echo "[entrypoint] start: $*"
exec "$@"

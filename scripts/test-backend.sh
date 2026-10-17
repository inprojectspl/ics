#!/usr/bin/env bash
# Run the backend test suite without the full compose stack.
# Uses ICS_DATABASE_URL / ICS_REDIS_URL when set; otherwise starts throwaway
# Postgres and Redis containers on fixed local ports and reuses them.
# Extra arguments go straight to pytest, e.g. scripts/test-backend.sh tests/test_config.py
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
pg_port="${ICS_TEST_PG_PORT:-5544}"
redis_port="${ICS_TEST_REDIS_PORT:-6390}"

ensure_container() {
  local name="$1" image="$2" port="$3" inner="$4"; shift 4
  if [ -z "$(docker ps -q -f "name=^${name}$")" ]; then
    docker rm -f "$name" >/dev/null 2>&1 || true
    docker run -d --name "$name" -p "127.0.0.1:${port}:${inner}" "$@" "$image" >/dev/null
  fi
}

if [ -z "${ICS_DATABASE_URL:-}" ]; then
  ensure_container ics-test-pg postgres:18.3-alpine "$pg_port" 5432 \
    -e POSTGRES_USER=ics -e POSTGRES_PASSWORD=ics -e POSTGRES_DB=ics
  until docker exec ics-test-pg pg_isready -U ics >/dev/null 2>&1; do sleep 1; done
  export ICS_DATABASE_URL="postgresql+asyncpg://ics:ics@localhost:${pg_port}/ics"
fi
if [ -z "${ICS_REDIS_URL:-}" ]; then
  ensure_container ics-test-redis redis:7-alpine "$redis_port" 6379
  export ICS_REDIS_URL="redis://localhost:${redis_port}/0"
fi

# Debug mode lets the default development secret key through the settings guard.
export ICS_DEBUG="${ICS_DEBUG:-1}"

cd "$root/backend"
exec uv run pytest "$@"

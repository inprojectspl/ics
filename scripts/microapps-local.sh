#!/usr/bin/env bash
# Local micro-application PoC profile (compose.microapps.local.yaml).
#
#   scripts/microapps-local.sh doctor   check the Docker context, inherited environment, env file, ports, TLS, MCP
#   scripts/microapps-local.sh init     create the git-ignored env file and keys, build images, migrate (no data reset)
#   scripts/microapps-local.sh up       start the stack, wait for readiness, print the local addresses
#   scripts/microapps-local.sh seed     idempotent test accounts; the two micro-applications go through local MCP
#   scripts/microapps-local.sh test     backend, runtime, MCP and frontend checks plus the acceptance run
#   scripts/microapps-local.sh down     stop this project's containers, keep the data
#   scripts/microapps-local.sh purge    delete this project's volumes (asks first)
#
# Every Compose call runs with a scrubbed environment (`env -i`), an explicit
# project name, file and env file, so ICS_DATABASE_URL, DOCKER_HOST or
# COMPOSE_PROJECT_NAME set in the shell can never redirect it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="ics-microapps-local"
COMPOSE_FILE_PATH="$ROOT/compose.microapps.local.yaml"
ENV_FILE="$ROOT/.env.microapps.local"
STATE_DIR="$ROOT/.microapps-local"
TLS_DIR="$STATE_DIR/tls"
CA_FILE="$STATE_DIR/local-ca.crt"
BASE_URL="https://ics.localhost:8443"
MCP_CHECKOUT="${ICS_MCP_CHECKOUT:-$(cd "$ROOT/.." && pwd)/ics-mcp}"
REQUIRED_KEYS=(PGADMIN_PASSWORD ICS_PG_PASSWORD ICS_APPS_PROVISIONER_PASSWORD ICS_SECRET_KEY
  ICS_MICROAPPS_SERVICE_TOKEN ICS_MICROAPPS_SESSION_SECRET ICS_BOOTSTRAP_ADMIN_PASSWORD
  ICS_LOCAL_USER_PASSWORD)

red() { printf '\033[31m%s\033[0m\n' "$*" >&2; }
ok() { printf '  ok    %s\n' "$*"; }
warn() { printf '  warn  %s\n' "$*"; }
fail() { printf '  FAIL  %s\n' "$*"; FAILED=1; }

docker_context() {
  # The context Docker would use, after DOCKER_CONTEXT and DOCKER_HOST.
  docker context show 2>/dev/null || echo default
}

LOCAL_CONTEXT=""
resolve_context() {
  local ctx endpoint
  ctx="$(docker_context)"
  endpoint="$(docker context inspect "$ctx" --format '{{.Endpoints.docker.Host}}' 2>/dev/null || true)"
  case "$endpoint" in
    unix://*) LOCAL_CONTEXT="$ctx"; return 0 ;;
    *) return 1 ;;
  esac
}

compose() {
  # Scrubbed environment: only what Docker itself needs to find its config.
  env -i PATH="$PATH" HOME="$HOME" ${DOCKER_CONFIG:+DOCKER_CONFIG="$DOCKER_CONFIG"} \
    docker --context "$LOCAL_CONTEXT" compose -p "$PROJECT" -f "$COMPOSE_FILE_PATH" \
    --env-file "$ENV_FILE" --project-directory "$ROOT" "$@"
}

env_value() {
  grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2-
}

doctor() {
  FAILED=0
  echo "ICS micro-application local profile: doctor"

  if ! command -v docker >/dev/null 2>&1; then fail "docker CLI not found"; return 1; fi
  if [ -n "${DOCKER_HOST:-}" ]; then
    case "$DOCKER_HOST" in
      unix://*) warn "DOCKER_HOST is set in the shell; the wrapper ignores it and uses the named context" ;;
      *) fail "DOCKER_HOST points to a non-local daemon ($DOCKER_HOST): unset it" ;;
    esac
  fi
  if resolve_context; then
    ok "Docker context '$LOCAL_CONTEXT' uses a local Unix socket"
  else
    fail "Docker context '$(docker_context)' is not a local Unix socket (remote daemon?)"
  fi
  if [ -n "$LOCAL_CONTEXT" ] && ! docker --context "$LOCAL_CONTEXT" info >/dev/null 2>&1; then
    fail "the local Docker daemon does not answer"
  fi

  local inherited
  inherited="$(env | cut -d= -f1 | grep -E '^(ICS_|COMPOSE_|PG(HOST|PORT|USER|PASSWORD|DATABASE)$|DATABASE_URL$|REDIS_URL$)' || true)"
  if [ -n "$inherited" ]; then
    warn "inherited variables are dropped by the wrapper: $(echo "$inherited" | tr '\n' ' ')"
  else
    ok "no ICS_/COMPOSE_/PG* variables inherited from the shell"
  fi

  if [ ! -f "$ENV_FILE" ]; then
    fail "$ENV_FILE missing: run '$0 init'"
  else
    local key missing=""
    for key in "${REQUIRED_KEYS[@]}"; do
      [ -n "$(env_value "$key")" ] || missing="$missing $key"
    done
    [ -z "$missing" ] && ok "env file has every required secret" || fail "env file lacks:$missing"
    if grep -Eiq '(inprojects\.ai|amazonaws\.com|r2\.cloudflarestorage|://[^/]*@?(db|pg|postgres)\.[a-z]+\.)' "$ENV_FILE"; then
      fail "env file references a non-local host"
    else
      ok "env file references local services only"
    fi
    if git -C "$ROOT" ls-files --error-unmatch "$ENV_FILE" >/dev/null 2>&1; then
      fail "env file is tracked by git"
    else
      ok "env file is ignored by git"
    fi
  fi
  if [ -f "$ROOT/.env" ]; then
    warn "$ROOT/.env exists; this profile never reads it"
  fi
  [ -f "$STATE_DIR/oauth.pem" ] && ok "local OAuth signing key present" || fail "local OAuth key missing: run '$0 init'"

  if [ "$FAILED" = 0 ] && [ -n "$LOCAL_CONTEXT" ]; then
    if compose config -q 2>/dev/null; then ok "compose configuration is valid"; else fail "compose config is invalid"; fi
    local other
    other="$(docker --context "$LOCAL_CONTEXT" ps --filter publish=8443 --format '{{.Label "com.docker.compose.project"}}' | grep -v "^$PROJECT$" || true)"
    if [ -n "$other" ]; then fail "port 8443 is published by another project: $other"; fi
    if ! docker --context "$LOCAL_CONTEXT" ps --format '{{.Names}}' | grep -q "^$PROJECT-proxy-"; then
      if lsof -nP -iTCP:8443 -sTCP:LISTEN >/dev/null 2>&1; then
        fail "port 8443 is taken by another process"
      else
        ok "port 8443 is free"
      fi
    else
      ok "port 8443 belongs to this project's proxy"
    fi
  fi

  if python3 - <<'PY' 2>/dev/null; then ok "*.localhost names resolve to loopback (wildcard app origins work)"; else fail "ics.localhost or *.ics-apps.localhost does not resolve to loopback"; fi
import ipaddress, socket, sys
for host in ("ics.localhost", "html.ics.localhost", "k7m2q9x4.ics-apps.localhost", "a-0123456789abcdef0123456789abcdef-prod.ics-apps.localhost"):
    for info in socket.getaddrinfo(host, 8443, proto=socket.IPPROTO_TCP):
        if not ipaddress.ip_address(info[4][0]).is_loopback:
            sys.exit(1)
PY

  if [ -f "$CA_FILE" ] && curl -fsS --max-time 5 --cacert "$CA_FILE" "$BASE_URL/healthz" >/dev/null 2>&1; then
    ok "HTTPS $BASE_URL verifies against the local CA ($CA_FILE)"
  else
    warn "HTTPS not verified yet (stack down or CA not exported; '$0 up' exports it)"
  fi

  if [ -d "$MCP_CHECKOUT/ics_mcp" ]; then
    ok "local ICS-MCP checkout: $MCP_CHECKOUT"
  else
    fail "ICS-MCP checkout not found at $MCP_CHECKOUT (set ICS_MCP_CHECKOUT)"
  fi
  if command -v claude >/dev/null 2>&1; then
    local mcp
    mcp="$(claude mcp get ics-local 2>/dev/null || true)"
    if [ -z "$mcp" ]; then
      warn "Claude Code has no 'ics-local' MCP server yet (see docs/development/microapps-local.md)"
    elif echo "$mcp" | grep -q "ics.localhost:8443" && echo "$mcp" | grep -q "ics-mcp-local-microapps" && echo "$mcp" | grep -q -- "$MCP_CHECKOUT"; then
      ok "MCP 'ics-local' runs the local checkout against $BASE_URL with its own credential profile"
    else
      fail "MCP 'ics-local' does not point at the local checkout, target and profile"
    fi
  fi

  if [ "$FAILED" != 0 ]; then red "doctor: problems found, nothing was started"; return 1; fi
  echo "doctor: ok"
}

rand() { openssl rand -hex "$1"; }

# The profile's own CA and one certificate for every local host, served by
# nginx. Config files instead of -addext keep LibreSSL (stock macOS) working.
local_tls() {
  mkdir -p "$TLS_DIR"
  chmod 700 "$TLS_DIR"
  if [ ! -f "$TLS_DIR/ca.key" ]; then
    (umask 077; openssl ecparam -name prime256v1 -genkey -noout -out "$TLS_DIR/ca.key")
    cat >"$TLS_DIR/ca.cnf" <<'CNF'
[req]
distinguished_name = dn
prompt = no
[dn]
CN = ICS micro-applications local CA
[v3_ca]
basicConstraints = critical,CA:TRUE,pathlen:0
keyUsage = critical,keyCertSign,cRLSign
subjectKeyIdentifier = hash
CNF
    openssl req -x509 -new -key "$TLS_DIR/ca.key" -sha256 -days 3650 -config "$TLS_DIR/ca.cnf" \
      -extensions v3_ca -out "$TLS_DIR/ca.crt"
    echo "created the local CA ($TLS_DIR/ca.crt)"
  fi
  # A new server certificate when missing, valid for less than 30 days or
  # not covering the app origins (they moved from *.apps.ics.localhost).
  if [ ! -f "$TLS_DIR/server.crt" ] || ! openssl x509 -checkend 2592000 -noout -in "$TLS_DIR/server.crt" >/dev/null 2>&1 \
    || ! openssl x509 -noout -checkhost a-0-prod.ics-apps.localhost -in "$TLS_DIR/server.crt" 2>/dev/null | grep -q "does match"; then
    cat >"$TLS_DIR/server.cnf" <<'CNF'
[req]
distinguished_name = dn
prompt = no
[dn]
CN = ics.localhost
[v3_server]
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature
extendedKeyUsage = serverAuth
# Python's strict verification (3.13+) requires both key identifiers.
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid
subjectAltName = DNS:ics.localhost,DNS:html.ics.localhost,DNS:*.ics-apps.localhost,DNS:mail.ics.localhost
CNF
    (umask 077; openssl ecparam -name prime256v1 -genkey -noout -out "$TLS_DIR/server.key")
    openssl req -new -key "$TLS_DIR/server.key" -config "$TLS_DIR/server.cnf" -out "$TLS_DIR/server.csr"
    openssl x509 -req -in "$TLS_DIR/server.csr" -CA "$TLS_DIR/ca.crt" -CAkey "$TLS_DIR/ca.key" \
      -CAcreateserial -days 397 -sha256 -extfile "$TLS_DIR/server.cnf" -extensions v3_server \
      -out "$TLS_DIR/leaf.crt" 2>/dev/null
    # Leaf plus CA, so a client pinning the CA sees it in the chain.
    cat "$TLS_DIR/leaf.crt" "$TLS_DIR/ca.crt" >"$TLS_DIR/server.crt"
    rm -f "$TLS_DIR/server.csr"
    TLS_RENEWED=1
    echo "issued the local server certificate"
  fi
  cp "$TLS_DIR/ca.crt" "$CA_FILE"
}

init() {
  mkdir -p "$STATE_DIR"
  chmod 700 "$STATE_DIR"
  if [ ! -f "$ENV_FILE" ]; then
    umask 077
    cat >"$ENV_FILE" <<EOF
# Generated by scripts/microapps-local.sh init for the local profile only.
# Never copy production values here.
PGADMIN_PASSWORD=$(rand 24)
ICS_PG_PASSWORD=$(rand 24)
ICS_APPS_PROVISIONER_PASSWORD=$(rand 24)
ICS_APPS_READER_PASSWORD=$(rand 24)
ICS_SECRET_KEY=$(rand 32)
ICS_MICROAPPS_SERVICE_TOKEN=$(rand 32)
ICS_MICROAPPS_SESSION_SECRET=$(rand 32)
ICS_BOOTSTRAP_ADMIN_PASSWORD=Local-Admin-$(rand 8)
ICS_LOCAL_USER_PASSWORD=Local-User-$(rand 8)
# Test-only publication fault hooks (scripts/microapps-local.sh test).
ICS_MICROAPPS_FAULT_INJECTION=true
EOF
    echo "created $ENV_FILE"
  else
    echo "keeping existing $ENV_FILE"
  fi
  if [ ! -f "$STATE_DIR/oauth.pem" ]; then
    (umask 077; openssl genrsa -out "$STATE_DIR/oauth.pem" 2048 2>/dev/null)
    # Read by the backend container user.
    chmod 644 "$STATE_DIR/oauth.pem"
    echo "created local OAuth signing key"
  fi
  doctor
  local_tls
  compose build
  compose up -d postgres redis
  compose run --rm migrate
  echo "init: done (data kept on re-run). Next: $0 up"
}

# The read-only role came after the first profiles: add what an older env
# file or cluster lacks. Idempotent.
reader_role() {
  if ! grep -q '^ICS_APPS_READER_PASSWORD=' "$ENV_FILE"; then
    echo "ICS_APPS_READER_PASSWORD=$(rand 24)" >>"$ENV_FILE"
  fi
}

reader_grants() {
  local pw
  pw="$(env_value ICS_APPS_READER_PASSWORD)"
  compose exec -T -u postgres postgres psql -q -v ON_ERROR_STOP=1 -U pgadmin -d postgres <<SQL >/dev/null
SELECT 'CREATE ROLE ics_apps_reader LOGIN NOINHERIT'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ics_apps_reader') \gexec
ALTER ROLE ics_apps_reader PASSWORD '$pw';
GRANT CONNECT ON DATABASE ics_apps TO ics_apps_reader;
SELECT pg_reload_conf();
SQL
  compose exec -T backend python -m app.cli microapps-grant-reader
}

up() {
  doctor
  reader_role
  TLS_RENEWED=0
  local_tls
  compose up -d
  # nginx reads the certificate at start: a running proxy needs a restart.
  if [ "$TLS_RENEWED" = 1 ]; then compose restart proxy >/dev/null; fi
  echo "waiting for the backend and the proxy..."
  local i
  for i in $(seq 1 90); do
    if curl -fsS --max-time 5 --cacert "$CA_FILE" "$BASE_URL/readyz" >/dev/null 2>&1; then break; fi
    sleep 2
  done
  curl -fsS --max-time 5 --cacert "$CA_FILE" "$BASE_URL/readyz" >/dev/null || { red "backend not ready behind the proxy"; exit 1; }
  # System roots plus the local CA, for SSL_CERT_FILE of Python clients (ICS-MCP).
  cat /etc/ssl/cert.pem "$CA_FILE" >"$STATE_DIR/ca-bundle.pem"
  reader_grants
  cat <<EOF
up: ready
  ICS panel            $BASE_URL            (admin@example.com, password in $ENV_FILE)
  HTML viewer          https://html.ics.localhost:8443
  Micro-applications   https://<8-character name>.ics-apps.localhost:8443 (app_url in ics_microapp_status)
  Mailpit              https://mail.ics.localhost:8443
  App data (read-only) postgres.ics-microapps-local.orb.local:5432/ics_apps, user ics_apps_reader (OrbStack)
  Local CA             $CA_FILE (trust it explicitly, see docs/development/microapps-local.md)
EOF
}

seed() {
  doctor
  local pass
  pass="$(env_value ICS_LOCAL_USER_PASSWORD)"
  for who in alice bob carol dave; do
    compose exec -T -e SEED_PASSWORD="$pass" backend python -m app.cli seed-user --email "$who@example.com" --password-env SEED_PASSWORD
  done
  echo "seed: accounts alice/bob/carol/dave@example.com, password ICS_LOCAL_USER_PASSWORD in $ENV_FILE"
  echo "seed: creating the two micro-applications through the local MCP server"
  (cd "$ROOT" && uv run --project "$MCP_CHECKOUT" --with playwright==1.65.1 python local/microapps/acceptance/seed_via_mcp.py)
}

run_tests() {
  doctor
  local rc=0
  echo "== backend (pytest inside the profile, local Postgres/Redis only)"
  compose run --rm --no-deps \
    -v "$ROOT/docs:/docs:ro" -v "$ROOT/frontend/src:/frontend/src:ro" -v "$ROOT/examples:/examples:ro" \
    -v "$ROOT/backend/app:/backend/app:ro" \
    -e ICS_DEBUG=1 -e ICS_SECRET_KEY=test-secret \
    -e ICS_DATABASE_URL="postgresql+asyncpg://ics:$(env_value ICS_PG_PASSWORD)@postgres:5432/ics" \
    -e ICS_REDIS_URL="redis://redis:6379/0" -e ICS_MICROAPPS_TEST_HBA=strict \
    -e ICS_MICROAPPS_TEST_PROVISIONER_URL="postgresql://ics_apps_provisioner:$(env_value ICS_APPS_PROVISIONER_PASSWORD)@postgres:5432/postgres" \
    backend sh -c 'for v in $(env | grep -o "^ICS_[A-Z0-9_]*"); do case $v in ICS_DATABASE_URL|ICS_REDIS_URL|ICS_DEBUG|ICS_SECRET_KEY|ICS_MICROAPPS_TEST_*) ;; *) unset "$v" ;; esac; done; cd /app && uv run --no-sync pytest -q -p no:cacheprovider --cov=app --cov-report=term:skip-covered --cov-fail-under=90' || rc=1
  echo "== microapp runtime (node --test)"
  compose run --rm --no-deps --entrypoint "" broker sh -c "node --test test/*.test.js" || rc=1
  echo "== ICS-MCP (ruff, mypy, pytest with the CI coverage gate)"
  (cd "$MCP_CHECKOUT" && uv run --extra dev ruff check . && uv run --extra dev ruff format --check . && uv run --extra dev mypy --strict ics_mcp && uv run --extra dev pytest -q --cov=ics_mcp --cov-fail-under=85) || rc=1
  echo "== frontend (typecheck, lint, unit tests)"
  compose run --rm --no-deps frontend sh -c 'npm run typecheck && npm run lint && npm test' || rc=1
  echo "== acceptance (local MCP + browser + failure scenarios)"
  (cd "$ROOT" && uv run --project "$MCP_CHECKOUT" --with playwright==1.65.1 python local/microapps/acceptance/run.py) || rc=1
  return $rc
}

down() {
  resolve_context || { red "no local Docker context"; exit 1; }
  compose stop
  echo "down: containers stopped, volumes kept"
}

purge() {
  resolve_context || { red "no local Docker context"; exit 1; }
  read -r -p "Delete all volumes of project $PROJECT (databases, storage, CA)? [yes/N] " answer
  [ "$answer" = "yes" ] || { echo "nothing deleted"; exit 0; }
  compose down -v
}

cmd="${1:-help}"
case "$cmd" in
  doctor) doctor ;;
  init) init ;;
  up) up ;;
  seed) seed ;;
  test) run_tests ;;
  down) down ;;
  purge) purge ;;
  compose) shift; doctor >/dev/null; compose "$@" ;;
  *) sed -n '2,12p' "$0"; exit 2 ;;
esac

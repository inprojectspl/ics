# Deploying ICS

This guide describes the reference production setup: one Linux host running
Docker Compose, PostgreSQL installed on the host, and a reverse proxy in a
separate Compose stack that terminates TLS. Other layouts work too (managed
PostgreSQL, S3 storage, a different proxy); the settings involved are listed
in [`.env.example`](https://github.com/inprojectspl/ics/blob/main/.env.example).

You build the backend and frontend images, push them to a container registry
and start the stack with the production Compose overlay ([step 4](#step-4-first-deployment)).
A CI pipeline can run the same commands on every push to `main`.

## Prerequisites on the target host

- Linux with at least 2 GiB RAM and 20 GiB disk.
- Docker Engine with the Compose v2 plugin.
- **PostgreSQL 18** installed on the host (see [step 2](#step-2-postgresql)),
  or a database elsewhere reachable through `ICS_DATABASE_URL`.
- **A reverse proxy** (for example nginx in its own Compose stack):
  - a Docker network named by `ICS_EDGE_NETWORK` (default `edge`) exists and
    the proxy container is attached to it;
  - the `ics_static` volume exists and is mounted into the proxy, read-only,
    at the web root (for nginx `/usr/share/nginx/html:ro`);
  - two host names point at it: the main app (`ics.example.com`) and the
    isolated HTML bundle origin (`html-ics.example.com`), both with TLS.
  [`docs/deploy/nginx.example.conf`](./deploy/nginx.example.conf) is a working
  server configuration; copy it to the proxy stack (for example
  `/etc/nginx/conf.d/ics.conf`) and replace the host names.

## Step 1: shared resources

Once, by hand, on the host:

```bash
docker volume create ics_static
docker network create edge   # or reuse the proxy's network and set ICS_EDGE_NETWORK=<name>
```

## Step 2: PostgreSQL

Once, as root on the host.

### Create the role and the database

```bash
sudo -u postgres psql
```

In psql (use the same password you will put into `ICS_PG_PASSWORD`):

```sql
CREATE ROLE ics WITH LOGIN PASSWORD '<password>';
CREATE DATABASE ics OWNER ics;
\q
```

### Accept connections from the Docker bridge

The backend reaches the host through `host.docker.internal`.

`/etc/postgresql/18/main/postgresql.conf`:

```
listen_addresses = '*'
```

`/etc/postgresql/18/main/pg_hba.conf` (add before the `# IPv4 local
connections` section):

```
host    ics    ics    172.16.0.0/12    scram-sha-256
```

Restart and check:

```bash
sudo systemctl restart postgresql

# From the host, over TCP (tests listen_addresses):
psql -h 127.0.0.1 -U ics -d ics

# From a container on the Docker bridge:
docker run --rm --add-host=host.docker.internal:host-gateway postgres:18.3-alpine \
  psql -h host.docker.internal -U ics -d ics -c '\conninfo'
```

Make sure a firewall keeps port 5432 closed to the outside.

## Step 3: configuration

Copy [`.env.example`](https://github.com/inprojectspl/ics/blob/main/.env.example) and fill it in. At minimum:

| Variable | Value |
|---|---|
| `ICS_SECRET_KEY` | `openssl rand -hex 32` |
| `ICS_PG_PASSWORD` | the password from step 2 (`openssl rand -base64 24`) |
| `ICS_BASE_URL` | `https://ics.example.com` |
| `ICS_HTML_VIEWER_BASE` | `https://html-ics.example.com` (must differ from `ICS_BASE_URL`) |
| `ICS_CORS_ORIGINS` | `https://ics.example.com` |
| `ICS_ALLOWED_DOMAINS` | your organisation's e-mail domains, CSV |
| `ICS_BOOTSTRAP_ADMIN_EMAIL` / `ICS_BOOTSTRAP_ADMIN_PASSWORD` | the first administrator |
| `ICS_EDGE_NETWORK` | the proxy network from step 1 |
| `ICS_SMTP_*` | your mail relay |
| `ICS_SYNC_IMAGE` | an `ics-sync` image, if you use GitLab bindings (see the [README](https://github.com/inprojectspl/ics/blob/main/README.md#gitlab-repository-bindings)) |

Never commit the filled-in `.env`. When a CI pipeline deploys, keep the
secrets (`ICS_SECRET_KEY`, `ICS_PG_PASSWORD`, `ICS_GOOGLE_OIDC_CLIENT_SECRET`,
`ICS_OAUTH_PRIVATE_KEY_PEM`) in its secret store and pass them only to the
deploy job.

## Step 4: first deployment

Build the images and push them to your registry:

```bash
export ICS_IMAGE_REGISTRY=registry.example.com/ics   # where the images live
export IMAGE_TAG=$(git rev-parse --short HEAD)       # default: latest
docker build --target prod -t $ICS_IMAGE_REGISTRY/backend:$IMAGE_TAG backend
docker build --target prod -t $ICS_IMAGE_REGISTRY/frontend:$IMAGE_TAG frontend
docker push $ICS_IMAGE_REGISTRY/backend:$IMAGE_TAG
docker push $ICS_IMAGE_REGISTRY/frontend:$IMAGE_TAG
```

Then start the stack on the host, next to the filled-in `.env`:

```bash
docker compose -p ics -f compose.yaml -f compose.prod.yaml up -d --pull always
```

The host does not need the repository: `docker compose -f compose.yaml -f
compose.prod.yaml config` renders one self-contained file that you can copy
there (or stream over SSH) and start with `docker compose -p ics -f - up -d`.

Then check on the host:

```bash
docker compose -p ics ps
# backend:    Up (healthy)
# arq-worker: Up
# ocr-worker: Up
# redis:      Up (healthy)
# frontend:   Exited (0)   <- one-shot copier, expected

# Static files in the volume:
docker run --rm -v ics_static:/static alpine ls /static
# index.html, assets/, ...

# Backend health through the proxy:
curl -fsS https://ics.example.com/healthz
```

Sign in as the bootstrap administrator. Afterwards change the password in the
app and remove `ICS_BOOTSTRAP_ADMIN_PASSWORD` from the configuration.

## Step 5: Google sign-in (optional)

1. In the Google Cloud Console, open *APIs & Services, Credentials* and
   create an *OAuth 2.0 Client ID* of type *Web application*.
2. Authorised redirect URI: `https://ics.example.com/api/auth/google/callback`
   (that is, `{ICS_BASE_URL}/api/auth/google/callback`).
3. Set `ICS_GOOGLE_OIDC_CLIENT_ID` and `ICS_GOOGLE_OIDC_CLIENT_SECRET`.
4. Recreate the backend, for example
   `docker compose -p ics -f compose.yaml -f compose.prod.yaml up -d --force-recreate backend`.
5. The login screen now shows the Google button. Only addresses in
   `ICS_ALLOWED_DOMAINS` can sign in.

## Step 6: MCP clients (optional)

Set `ICS_OAUTH_PRIVATE_KEY_PEM` (or `ICS_OAUTH_PRIVATE_KEY_PEM_PATH`; generate
with `openssl genrsa -out priv.pem 2048`) and `ICS_MCP_RESOURCE_URI`.
Set `ICS_OAUTH_ISSUER` to the externally reachable ICS origin (for example
`https://ics.example.com`) and use the same MCP resource URI in ICS and `ics-mcp`.
The reverse proxy must forward `/api/` and these exact root paths to the backend:

- `/.well-known/oauth-protected-resource`
- `/.well-known/oauth-authorization-server`
- `/.well-known/openid-configuration`

The example nginx config (`docs/deploy/nginx.example.conf`) includes all three.
After updating the backend, update and reload the edge config too. Check that each
path returns JSON, not the SPA's HTML with a misleading `200` status. The older
discovery URLs under `/api/auth/oauth/.well-known/` remain available.

An MCP connection can start without an existing ICS session. Sign in with Google
or a password, then return to the original OAuth consent request. Google sign-in
uses the callback from Step 5; a ChatGPT callback belongs to the MCP OAuth client,
not the Google Cloud client. ICS supports dynamic client registration, so the
connector can register its own callback without changing the built-in Claude client.
Test both a fresh browser session and a previously signed-in session before rollout.

## Step 7: notifications

Design: `docs/decisions/0023-notifications.md`. In-app notifications work
without configuration; the rest needs:

- **Browser notifications (Web Push).** Generate a key pair once and put it
  in `.env`; changing it later invalidates every registered device.

  ```bash
  docker compose run --rm backend python -m app.cli vapid-keygen
  # ICS_VAPID_PRIVATE_KEY=...   ICS_VAPID_SUBJECT=mailto:ops@example.com
  ```

  The worker contacts the push services of the browsers
  (`fcm.googleapis.com`, `updates.push.services.mozilla.com`,
  `web.push.apple.com`, `*.notify.windows.com`) over HTTPS; allow that egress.
- **E-mail.** The worker sends the notification e-mails, so it needs the
  same `ICS_SMTP_*` as the backend (already passed in `compose.yaml`).
- **Proxy.** The live stream `/api/notifications/stream` must not be
  buffered and needs a long read timeout; `/sw.js` and
  `/manifest.webmanifest` must not be cached. The example nginx config has
  all three locations; with your own proxy, copy them.
- **Redis.** Inboxes are kept in Redis (about 50 KB per active user at most).
  The production limit is 512 MB. To keep inboxes, sessions and queued jobs
  across a Redis restart, enable AOF on the running instance first, then
  make it permanent; turning `appendonly` on only in the command line of an
  instance that has an RDB snapshot but no AOF starts it empty:

  ```bash
  docker compose exec redis redis-cli CONFIG SET appendonly yes
  # wait until `INFO persistence` shows aof_rewrite_in_progress:0, then add
  # `--appendonly yes` to the redis command in your compose override
  ```

## Backups

PostgreSQL runs on the host, so database backups are the host's job
(`pg_dump` from cron, WAL archiving, volume snapshots). The repository does not
ship a backup script.

Document files:

- `fs://` (default): the `asset_storage` Docker volume. Back it up from the
  host, for example with `tar` over
  `/var/lib/docker/volumes/ics_asset_storage/_data`.
- `s3://`: use the provider's versioning and replication.

## Updates

Every deployment pulls new images and recreates the containers. The
production backend image runs `alembic upgrade head` on start
(`backend/docker-entrypoint.sh`). To run migrations yourself instead, set
`ICS_SKIP_MIGRATIONS=1` in the backend service environment; `compose.yaml`
does not pass it through, so add it there first.

## Rollback

Redeploy the previous image tag:

```bash
IMAGE_TAG=<previous-tag> ICS_IMAGE_REGISTRY=registry.example.com/ics \
  docker compose -p ics -f compose.yaml -f compose.prod.yaml up -d --pull always
```

If the newer version ran a migration you need to undo, restore the database
backup and deploy the version from before the migration. Treat migrations as
one-way: Alembic has `downgrade()`, but a dropped column does not come back
with its data.

## Troubleshooting

```bash
docker compose -p ics logs -f            # all services
docker compose -p ics logs -f backend
docker compose -p ics restart backend
docker compose -p ics exec backend bash
psql -h 127.0.0.1 -U ics -d ics          # host database
```

Common problems:

- **The backend refuses to start because of `ICS_SECRET_KEY`**: the default
  development key is rejected unless `ICS_DEBUG=1`. Generate a key, set it,
  recreate the container.
- **Missing certificate or 502 from the proxy**: check the proxy logs, that the
  backend container is on the `ICS_EDGE_NETWORK` network, and that
  `ics_static` contains a fresh `index.html`.
- **Google sign-in fails**: the redirect URI in the Google Console must match
  `{ICS_BASE_URL}/api/auth/google/callback` exactly (scheme, host, port,
  path).
- **Backend health check stays unhealthy**: read `docker compose -p ics logs
  backend`; the usual cause is a database password mismatch.
- **403 `csrf_origin_rejected`** on forms and uploads: the browser origin is
  not `ICS_BASE_URL` or one of `ICS_CORS_ORIGINS`.

## Security checklist before opening to users

- [ ] `ICS_SECRET_KEY` is a fresh `openssl rand -hex 32`, not the default.
- [ ] `ICS_PG_PASSWORD` is strong and unique.
- [ ] `ICS_DEBUG=0` and `ICS_DEV_STUB_SSO=false`.
- [ ] The bootstrap administrator password was changed after the first
      sign-in.
- [ ] Backups run daily and are monitored.
- [ ] HTTPS works for both host names.
- [ ] `ICS_HTML_VIEWER_BASE` is a different host from `ICS_BASE_URL`.
- [ ] `ICS_ALLOWED_DOMAINS` lists **only** your organisation's e-mail
      domains; they can sign in through SSO and open `org_sso` links.

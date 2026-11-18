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

## Micro-applications (optional)

Small apps with their own data (`micro_application` assets), run by a shared
broker and two runner supervisors from the `microapp-runtime` image. Every
app gets its own origin `https://<name>.<suffix>`, `name` being 8 random
characters reserved for that app for good (the long
`https://a-<asset id hex>-prod.<suffix>` of earlier releases keeps working). Off unless
`compose.microapps.yaml` is part of the deployment (`ICS_MICROAPPS_ENABLED`
defaults to false). A lighter ICS leaves the overlay out and needs none of
this section: no broker or runners, no `ics_apps` database, no second domain;
the micro-application API, an app's version history and app links answer
`microapps_disabled`, publications wait, and the UI shows no micro-application
settings. Existing app assets stay listed (title and summary); opening one
says that micro-applications are off.

### A domain of their own

Apps run code that people and agents write, so they live on a separate
registrable domain, not under the ICS domain: `example.net` for an ICS on
`ics.example.com`. Under the ICS domain an app would be the same site as
ICS: its script could set cookies for ICS hosts, and same-site requests to
ICS would carry the visitor's cookies. GitHub and Google keep user content
on separate domains for the same reason. `ICS_MICROAPPS_APP_HOST_SUFFIX` is
that domain; an app host is one label under it (`k7m2q9x4.example.net`, or
the long `a-<32 hex>-prod.example.net`).

### DNS and certificates with Cloudflare

The simplest setup, and no certbot with a DNS challenge:

1. Add the apps domain as a zone in Cloudflare (the Free plan is enough).
2. DNS: a proxied (orange cloud) record `*` to the address of the proxy.
3. Browser certificate: Universal SSL for `*.example.net`, issued and
   renewed by Cloudflare. It covers one level, which is all an app host has.
4. Origin certificate for nginx: a Cloudflare Origin CA certificate for
   `*.example.net` (made once in the dashboard, valid up to 15 years);
   SSL/TLS mode **Full (strict)**.
5. Optional: Authenticated Origin Pulls, so the apps server block accepts
   only Cloudflare (`ssl_verify_client`), and `real_ip_header
   CF-Connecting-IP` for real client addresses in the logs (both in the
   nginx example).

In the zone, turn off what rewrites pages: Rocket Loader, Email Obfuscation
and automatic Web Analytics injection (the apps' CSP allows only their own
scripts), and keep bot challenges off for it (an API call would get a
challenge page instead of JSON). Apps send `no-store` for HTML and API
answers and `private` for their files, so Cloudflare caches none of them;
do not add a "cache everything" rule. Cloudflare terminates TLS and sees
the apps' traffic: check that this fits your data policy.

Without Cloudflare: a wildcard DNS record and a wildcard certificate for
`*.example.net` from any CA (Let's Encrypt needs a DNS-01 challenge for a
wildcard).

### Proxy

Add the apps server blocks and the `ics_broker`
upstream from [`deploy/nginx.example.conf`](deploy/nginx.example.conf), and
check the two changes in the main `ics.example.com` block:

- `location ^~ /api/internal/ { return 404; }`: the broker's API to ICS must
  stay on the private network;
- `proxy_set_header X-ICS-Service-Token "";` in `/api/`: a client must not be
  able to send the broker's credential.

The broker sees the app from the `Host` header, so pass it unchanged. The
broker's admin port 8081 is never routed. `nginx -t && nginx -s reload`.

A short app host (`k7m2q9x4.example.net`) the broker has not seen yet costs
one internal lookup in ICS; known names are cached and unknown ones answer
404. The broker sets no budget for these lookups (a shared one would let
made-up names lock real visitors out), so limit requests per client on the
apps server block, with the real client address when behind Cloudflare:

```nginx
# http {}
limit_req_zone $binary_remote_addr zone=microapps:10m rate=50r/s;
# the apps server block on 8443
limit_req zone=microapps burst=100 nodelay;
```

Raise the rate when many people reach the apps from one address (an office
behind NAT).

### PostgreSQL

Apps keep their data in a separate database, `ics_apps`, one schema and one
runtime role per app. ICS creates them through a provisioner role that can
create roles but owns nothing in the ICS database. As `postgres` on the host:

```sql
CREATE ROLE ics_apps_provisioner LOGIN CREATEROLE PASSWORD '<ICS_APPS_PROVISIONER_PASSWORD>';
-- Ends the sessions of an app's runtime role before dropping it, when the app
-- is deleted for good (its owner or the asset row removed; the trash keeps it).
GRANT pg_signal_backend TO ics_apps_provisioner;
CREATE DATABASE ics_apps OWNER ics_apps_provisioner TEMPLATE template0;
REVOKE ALL ON DATABASE ics_apps FROM PUBLIC;
\c ics_apps
REVOKE ALL ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO ics_apps_provisioner;
```

`pg_hba.conf`, above the line for `ics` (order matters: the `reject` keeps
app roles out of every other database):

```
host    ics_apps    /^ma_[0-9a-f]{32}(_pv)?_run$    172.16.0.0/12    scram-sha-256
host    all         /^ma_                           all              reject
host    ics_apps    ics_apps_provisioner            172.16.0.0/12    scram-sha-256
```

Optionally, a read-only login for database tools (DBeast, DBeaver, psql)
and reports. ICS grants it `SELECT` on every app's tables, also on tables
later releases add, and the publication check fails if it can write:

```sql
CREATE ROLE ics_apps_reader LOGIN NOINHERIT PASSWORD '<password>';
GRANT CONNECT ON DATABASE ics_apps TO ics_apps_reader;
```

```
host    ics_apps    ics_apps_reader    <your admin network>    scram-sha-256
```

Set `ICS_MICROAPPS_READER_ROLE=ics_apps_reader` and, once, for apps that
already exist: `docker compose exec backend python -m app.cli
microapps-grant-reader`. The role sees every record of every app,
regardless of the apps' roles and row scopes: give it to administrators
only.

`max_connections` must leave room for the broker's pool
(`ICS_MICROAPPS_DB_MAX_CONNECTIONS`, default 24) on top of ICS. Reload
(`sudo systemctl reload postgresql`) and include `ics_apps` in the backups.

### Image

Build `microapp-runtime/` and push it next to the backend image, with the
same tag:

```bash
docker build -t "$ICS_IMAGE_REGISTRY/microapp-runtime:$IMAGE_TAG" microapp-runtime
docker push "$ICS_IMAGE_REGISTRY/microapp-runtime:$IMAGE_TAG"
```

### Configuration

In `.env` (see `.env.example`):

| Variable | Value |
|---|---|
| `ICS_MICROAPPS_APP_HOST_SUFFIX` | the apps domain, e.g. `example.net` |
| `ICS_APPS_PROVISIONER_PASSWORD` | the provisioner password above (`openssl rand -base64 24`) |
| `ICS_MICROAPPS_SERVICE_TOKEN` | `openssl rand -hex 32` |
| `ICS_MICROAPPS_SESSION_SECRET` | `openssl rand -hex 32`, different from the token |

Keep the three secrets with the others in the CI secret store.

### Deploy and check

```bash
docker compose -p ics -f compose.yaml -f compose.prod.yaml -f compose.microapps.yaml up -d --pull always
docker compose -p ics -f compose.yaml -f compose.prod.yaml -f compose.microapps.yaml ps
# broker, runner-1, runner-2: Up
```

The migrations run with the backend as usual. Then publish the template app
through MCP (`ics_microapp_contract(section="template")`, `ics_microapp_plan`,
`ics_microapp_apply`), give yourself a role with `ics_microapp_access_set`
and open its `app_url`. Each user's total app data is limited
(`users.microapp_data_max_bytes`, 100 MiB by default, changed in the admin
panel).

To turn the feature off again, deploy without the overlay: the app API
answers `microapps_disabled`, their data stays in `ics_apps`, and a rollback
or a later deploy must keep `-f compose.microapps.yaml` to keep them on.

## Backups

PostgreSQL runs on the host, so database backups are the host's job
(`pg_dump` from cron, WAL archiving, volume snapshots). The repository does not
ship a backup script.

Document files:

- `fs://` (default): the `asset_storage` Docker volume. Back it up from the
  host, for example with `tar` over
  `/var/lib/docker/volumes/ics_asset_storage/_data`.
- `s3://`: use the provider's versioning and replication.

Deleted documents wait in the trash for `ICS_TRASH_RETENTION_DAYS` (30 by
default); the worker then deletes them with their files every hour
([ADR-0029](decisions/0029-asset-archive-and-trash.md)). After that only a
backup brings a document back, so keep backups at least that long.

## Updates

Every deployment pulls new images and recreates the containers. The
production backend image runs `alembic upgrade head` on start
(`backend/docker-entrypoint.sh`). To run migrations yourself instead, set
`ICS_SKIP_MIGRATIONS=1` in the backend service environment; `compose.yaml`
does not pass it through, so add it there first.

## Rollback

Redeploy the previous image tag with the same files as the deployment (add
`-f compose.microapps.yaml` when micro-applications are on, or the rollback
turns them off):

```bash
IMAGE_TAG=<previous-tag> ICS_IMAGE_REGISTRY=registry.example.com/ics \
  docker compose -p ics -f compose.yaml -f compose.prod.yaml up -d --pull always
```

With micro-applications, `ics` and `ics_apps` restore together from backups
of the same moment: an app's schema version is recorded in `ics`, its tables
and migration log in `ics_apps`.

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

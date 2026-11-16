# Micro-applications: local PoC

A self-contained local profile for the micro-application proof of concept:
the ICS backend (Python) with plan/apply, one shared Node.js broker, two
QuickJS/WASM runner slots, a separate `ics_apps` database with a schema and
roles per app, and local HTTPS for the panel and every app origin. Adding an
app never adds a container or a process.

This is a PoC of the `ics.microapp/v1alpha1` contract, not a production
deployment; the limitations are listed at the end.

## What runs

| Service | Role |
| --- | --- |
| `proxy` (nginx, as in production) | HTTPS on `:8443` for `ics.localhost`, `html.ics.localhost`, `*.ics-apps.localhost` (a site of its own, as recommended for production), `mail.ics.localhost` with a certificate from the profile's own CA. Blocks `/api/internal/*` and strips identity headers: the rules of `docs/deploy/nginx.example.conf`, in `local/microapps/nginx`. |
| `backend`, `arq-worker` | ICS with the management API, durable publication operations, provisioning, measurements and cleanup. |
| `migrate` | One-shot `alembic upgrade head` before the backend starts. |
| `broker` | Gateway of every app origin: app sessions, generic CRUD, idempotency, custom endpoint execution. Connects to `ics_apps` only with each app's runtime role. |
| `runner-1`, `runner-2` | Runner supervisors, `network_mode: none`, read-only, 256 MiB, no secrets; Unix socket to the broker. A child process per lease key, a fresh WASM instance per call. |
| `postgres` | `ics` (metadata) and `ics_apps` (app data). HBA lets `ma_*_run` roles into `ics_apps` only. |
| `redis`, `mailpit`, `frontend` (Vite) | As in development. |

Addresses:

- ICS panel: <https://ics.localhost:8443> (micro-applications are in the document list, filter *Type: Micro-applications*; the old `/microapps` link opens it)
- HTML viewer: <https://html.ics.localhost:8443>
- Apps: `https://a-<asset id hex>-prod.ics-apps.localhost:8443/`
- Mail: <https://mail.ics.localhost:8443>
- App data, read-only, for database tools (DBeast, DBeaver, psql): host
  `postgres.ics-microapps-local.orb.local` (OrbStack; the database is not
  published on a localhost port), port 5432, database `ics_apps`, user
  `ics_apps_reader`, password `ICS_APPS_READER_PASSWORD` in
  `.env.microapps.local`. Each app is the schema `a_<asset id hex>`; the role
  reads every table and writes none. `up` creates the role in an older
  profile and grants it the existing apps.

## Start

Requirements: a local Docker engine (OrbStack, Docker Desktop, Colima), `uv`,
`openssl`, the ICS-MCP checkout next to this repository (or
`ICS_MCP_CHECKOUT=/abs/path`).

```bash
scripts/microapps-local.sh doctor   # checks before anything starts
scripts/microapps-local.sh init     # env file, keys, images, migrations (keeps data)
scripts/microapps-local.sh up       # stack, readiness, CA export, addresses
scripts/microapps-local.sh seed     # accounts + both pilot apps through local MCP
scripts/microapps-local.sh test     # backend, runtime, MCP, frontend, acceptance
scripts/microapps-local.sh down     # stop, keep data
scripts/microapps-local.sh purge    # delete this project's volumes (asks)
```

`init` writes `.env.microapps.local` (git-ignored) with new random secrets
and `.microapps-local/oauth.pem`; it never copies `.env`. Every Compose call
runs with a scrubbed environment (`env -i`), an explicit project name, file
and env file, so `ICS_DATABASE_URL`, `DOCKER_HOST` or `COMPOSE_PROJECT_NAME`
from the shell cannot redirect it. `doctor` refuses a remote Docker context,
non-local hosts in the env file, a port taken by another project and an
`ics-local` MCP entry that points elsewhere.

Accounts after `seed`: `admin@example.com` (password
`ICS_BOOTSTRAP_ADMIN_PASSWORD`) and `alice`, `bob`, `carol`, `dave` at
`example.com` (password `ICS_LOCAL_USER_PASSWORD`), both in the env file.

### Trusting the local CA

`init` and `up` create the profile's own CA in `.microapps-local/tls`
(`openssl`, kept between runs) and a certificate for every local host,
renewed when it has less than 30 days left. Only the server certificate and
key are mounted into nginx; the CA key never enters a container. `up` copies
the CA to `.microapps-local/local-ca.crt` and writes a bundle for Python
clients to `.microapps-local/ca-bundle.pem`. To open the apps in your own
browser, trust the CA once (a deliberate step, macOS):

```bash
security add-trusted-cert -r trustRoot -k ~/Library/Keychains/login.keychain-db .microapps-local/local-ca.crt
```

Remove it later with Keychain Access. Never disable TLS verification instead.
The acceptance scripts pin the local CA chain in Chromium
(`--ignore-certificate-errors-spki-list`) and pass the bundle to Python
through `SSL_CERT_FILE`.

## Local MCP connection

The pilots are created through the local ICS-MCP checkout, never through a
connector of another ICS instance. Claude Code entry (local scope):

```bash
claude mcp add ics-local --scope local \
  -e ICS_BASE_URL=https://ics.localhost:8443 \
  -e ICS_MCP_RESOURCE_URI=https://ics.localhost:8443/mcp \
  -e ICS_MCP_KEYRING_SERVICE=ics-mcp-local-microapps \
  -e ICS_MCP_TOKEN_FALLBACK_PATH="$PWD/.microapps-local/mcp-credentials-claude.json" \
  -e SSL_CERT_FILE="$PWD/.microapps-local/ca-bundle.pem" \
  -- uv run --project /abs/path/to/ics-mcp ics-mcp
```

A separate keyring service and token file make it a fresh credential profile;
nothing is imported from an existing one. After a restart of Claude Code the
eight tools `ics_microapp_*` appear (contract, plan, apply, status, control,
logs, access, access_set); the first call opens the local login.

`seed` and the acceptance run use the same entrypoint with one profile per
test user (`.microapps-local/mcp-credentials-<user>.json`, no OS keyring) and
complete the OAuth login in a headless Chromium with the local password.

## Manual check

1. `doctor`, `up`, `seed`. Sign in to the panel as `alice`, filter the
   documents by the micro-application kind: *Request register* and
   *Equipment booking* show
   *Enabled*, *Sleeping: no resources* (or *Ready* after use), active release,
   data size once measured. There is no upload or create form.
2. Open *Request register* as `bob` (Open, or the app URL). Submit a request,
   edit it, delete another one.
3. As `carol` (role *Reviewer* plus single permissions to file her own
   requests) open the same app: the request is in *To approve*; approve
   it. As `bob` the request shows `approved` and can no longer be edited.
4. As `dave` the app opens but shows no permissions; the API answers 403.
5. On the app's asset page, tab *Access*: `bob` holds the role *Employee*.
   Take it away and give single permissions without `requests.read`; his open
   tab gets 403 on the next action. Give the role back.
6. *Equipment booking*: as `alice` add equipment (quantity 2); as `bob`
   reserve and cancel; availability changes in both tables together.
7. Suspend *Request register* in the panel (or `ics_microapp_control`): the
   app answers 503 `app_suspended`. `scripts/microapps-local.sh compose
   restart broker backend arq-worker`: it stays suspended. Enable it: state
   *Enabled* + *Sleeping* until the next request.
8. Ask an agent (`ics-local`) to change an app: `ics_microapp_plan` with the
   changed package, `ics_microapp_apply`, `ics_microapp_status`. Repeat the
   apply: the same `operation_id` comes back.

## Limits

- Data: every user has `microapp_data_max_bytes` (default 100 MiB, set by an
  admin in the user dialog, audited), the total of all micro-applications
  they own. Over it, inserts and updates answer 507
  `app_data_quota_exceeded`; reads and deletes still work. The worker
  measures every 30 s and publishes the owners over their limit to Redis;
  each request reads one flag, so the cap is soft by one interval.
- Requests: token buckets per app and person
  (`ICS_MICROAPPS_RATE_USER_PER_SECOND`, default 20 a second, bursts of 40)
  and, for share-link visitors, per link (`ICS_MICROAPPS_RATE_LINK_PER_SECOND`,
  default 100, bursts of 200). They are checked on the session cookie
  before ICS is asked anything, kept in Redis (`ICS_MICROAPPS_REDIS_URL`) and
  shared by every broker process; without Redis each process counts alone.

## Fault hooks (local profile only)

With `ICS_MICROAPPS_FAULT_INJECTION=true` (set by `init`), the worker reads
`microapp:fault:<plan_id>` from Redis once: `fail:<step>` ends the operation
as failed, `crash_after:<step>` leaves it running with its lease as a dead
worker would (the sweeper resumes it). Steps: `package`, `provision`,
`migrate`, `verify`, `activate`. The setting is off by default everywhere
else.

## Differences from the target host and open points

- Runners are two Compose containers with memory, PID and CPU limits instead
  of `ics-runner@1/2.service` with cgroup v2 units; the target layout needs
  its own test.
- `arq --watch` does not see bind-mount changes under OrbStack: restart
  `arq-worker` together with `backend` after changing backend code. The
  worker runs publications (migration, seed rows), so a stale worker
  publishes with the old code.
- Preview environments (`_pv` schema, synthetic fixtures) are not built: the
  plan validates, compiles handlers and computes the migration, but runs no
  scenarios (`validation.preview = "not_run"`).
- Restore to a new data generation, a full data export (an agent reads the
  records each person may list through the document view), rotation of
  runtime credentials and per-person review assignment are not implemented.
- The OAuth token profile binding (issuer/base URL in `TokenPair`) is not
  added to ICS-MCP; the PoC relies on a fresh, separate profile.
- Statistics are polled (broker report every 10 s, DB size every 30 s).
- No load test of 100 apps was run.

## Sharing through a tunnel

To let someone outside try one app, expose the two loopback entry points of
the proxy (`127.0.0.1:8481` panel and API, `127.0.0.1:8482` app origin) with
a tunnel agent such as ngrok, with basic auth, and declare the public hosts
in `.env.microapps.local`:

```bash
ICS_PUBLIC_EXTRA_ORIGINS=,https://<panel tunnel host>
ICS_MICROAPPS_PUBLIC_ALIASES=<app tunnel host>=<asset id hex>
ICS_MICROAPPS_PUBLIC_ICS_URL=https://<panel tunnel host>
ICS_SHARE_BASE_URL=https://<panel tunnel host>
```

then `scripts/microapps-local.sh compose up -d backend arq-worker broker`.
The alias is an exact host mapped to exactly one app; sessions, CSRF and the
sign-in flow work as on the local origins. Remove the four lines and the
tunnels to stop sharing.

A share link (`/s/<token>`, created in the share dialog or with
`ics_share_create_link(app_roles=[...])`) opens the app without an ICS
account. The owner (manage right) picks which of the release's roles (or
single permissions) the link grants. ICS checks the link's gate (password, expiry, view limit) on
its own origin, then the broker gives the visitor an anonymous identity for
30 days, so their records stay theirs on the next visit. Every request is
authorized against the link: revoking it cuts open sessions at once. A member who
may already use the app (a role on the asset) enters through the same link as
themselves, with their own grants, and is not counted against `max_views`;
an app session they already have is kept.

A `public` link opens the app without any sign-in. Every other mode keeps its
gate as for documents: `password` asks for the password, `org_sso` for a
sign-in in the allowed domain, `magic_email` for the link from the message.
There is no sign-in-free entry other than a share link.


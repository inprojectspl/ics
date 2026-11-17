# Short micro-application hosts

Status: accepted (changes the app origin of [ADR-0027](0027-micro-applications.md))

## Context

Every micro-application runs on its own origin under a registrable domain
separate from ICS. The first releases derived the host from the asset id:
`https://a-89ff741c3ab14646ad8c8df1ecd7b872-prod.example.net/`. That address
is 50 characters of hex people copy, read out and paste into chats, and it
exposes the full asset id and the environment name in every link.

## Problem

Shorten the public address without giving up what the long one was for: one
origin per app (cookies, storage and CSP never shared), a host-bound session,
and no way to reach another app by changing the address.

## Decision

Options considered:

1. **Keep `a-<hex>-prod`.** No work; the address stays long.
2. **Paths under one host (`apps.example.net/a/<id>/`).** Short, but every
   app shares one origin, so one app's script reads another's storage and
   cookies. Rejected.
3. **A random short label per app, reserved for good (chosen).** Small
   change: a registry table, a lookup in ICS and the broker.

Each app environment gets a random 8-character label from the readable slug
alphabet of `app/slug.py` (31 characters, about 8.5e11 names):
`https://k7m2q9x4.example.net/`. The domain stays
`ICS_MICROAPPS_APP_HOST_SUFFIX`.

- **Drawn once, kept for good.** The name is stored in `microapp_host_names`
  (primary key `name`, unique `(asset_id, environment)`) and referenced by
  `microapp_environments.host_name`. Releases, restarts and control actions do
  not touch it. The asset id, `asset_hex`, schema and role names keep their
  meaning.
- **Never reused.** The registry has no foreign key to the asset and its rows
  are never deleted, so a deleted or purged app keeps its name and a new app
  cannot inherit an old link.
- **Collisions.** The primary key decides; allocation inserts with
  `ON CONFLICT DO NOTHING` and draws again, so two parallel creations never
  get the same name and the caller's transaction stays usable. A name whose
  host is a configured public alias is never handed out.
- **Trusted mapping.** A short label carries no id. The broker asks ICS
  (`POST /api/internal/microapps/hosts/resolve`, service token) which app and
  environment a short host is, checks the answer, and caches it (a name never
  moves to another app); unknown names are refused with 404 and remembered for
  ten seconds. ICS checks the exact host and the configured suffix. The name
  identifies the app, it never authorizes anything: the host-bound session,
  the one-time launch code, Origin and CSRF checks and the per-request
  authorization stay as they were.
- **Old addresses keep working.** `a-<hex>-prod.<suffix>` and configured
  aliases serve the same app, including its API and the sign-in callback. They
  are not redirected: a redirect would drop the session and break requests in
  flight. API responses, the panel and share links (`/s/<token>`) use the
  short address; a configured alias still replaces it, as before.
- **Existing apps.** Migration 0051 draws names for every existing
  environment.

## Consequences

- An origin change is a new site for the browser. Moving to the short address
  does not carry over the app session cookie, `localStorage` or the anonymous
  identity of a share-link visitor; people sign in again (automatically, if
  they are signed in to ICS), and a link visitor gets a new anonymous identity
  on the new host, so records they created as a guest on the old host are no
  longer theirs there. The old host keeps their session, storage and identity.
- The broker makes one extra internal call per short host until it is cached.
- Downgrading migration 0051 drops the reservations.

## Reactivation trigger

Revisit if apps need more than one environment per asset with separate
public names, or if an app needs a name chosen by its owner (which would need
review for confusable or offensive names).

# Micro-applications

Status: accepted (proof of concept behind `ICS_MICROAPPS_ENABLED`)

## Context and problem

Teams ask agents for small tools rather than documents: a request register,
a booking sheet, a poll. An HTML bundle can show such a tool but cannot keep
its data, and a separate hosted app for each request would bring its own
accounts, sharing and backups. ICS already knows who may see what, keeps
versions and history, and lets agents work with the user's permissions. The
question was how to run code that people and agents write, with its own data,
inside that model without letting one app reach ICS, another app or data its
users may not see.

## Decision

A micro-application is an asset of kind `micro_application`: listed, shared,
watched, versioned and deleted like any document, with a package of files
described by a manifest (`ics.microapp/v1alpha1`).

- **Agents publish, through a plan.** There is no upload form. An agent sends
  a complete package to `plan`, which checks it against the contract and binds
  it to a digest without touching the running app; `apply` publishes exactly
  that package as a durable, idempotent operation. Generic upload, edit,
  restore, sync and download routes refuse the kind.
- **One database, a schema and a role per app.** App data lives in a separate
  `ics_apps` database. Each app gets its own schema and a runtime role that
  reaches only that schema. The manifest declares collections, fields, indexes
  and seed rows; v1 accepts additive schema changes only.
- **A shared broker and sandboxed runners.** One Node.js broker serves every
  app origin: sessions, CSRF, generic CRUD with row scopes, idempotency and
  request budgets. Custom endpoints are JavaScript handlers run by two runner
  supervisors without network or secrets, in a fresh QuickJS/WASM instance per
  call, with limits on time, CPU, memory and database calls. Adding an app adds
  rows, not containers or processes; an idle app sleeps.
- **An origin per app on a domain of its own.** Every app runs on
  `a-<asset id>-<environment>.<suffix>`, under a registrable domain separate
  from ICS, so an app's script cannot set cookies for ICS or ride on its
  same-site requests. The app session is host-bound and obtained through ICS
  with a one-time code.
- **The app's roles are its own.** The manifest declares permissions and roles.
  ICS roles (viewer, editor, owner) decide what a person does with the asset,
  never in the app; even ownership implies no app role. Owners of the asset or
  its project give roles to people and projects; share links name the roles
  they give. A role means what the active release defines.
- **A document view for agents.** Every app declares a read-only endpoint that
  renders its content as Markdown. ICS runs it as the reader inside the data
  export, so an agent reading an app gets the same view and records the person
  would, under one authorization.
- **Releases are versions.** Each publication is a package version in the
  asset's history, with its release state, change note and `app_changes`
  (roles, permissions, endpoints, capabilities, collections). Publishers
  compare them with the generic version routes; restore is not offered.
- **Quotas.** Package files count against the owner's storage quota; app data
  counts against a per-owner micro-application data limit.

## Options considered

- **A container per app.** Strong isolation, but every app would cost a
  process, memory and an operator's attention, and idle apps could not be
  folded away. Rejected for a feature meant for many small tools.
- **Apps under the ICS domain.** Simpler DNS and certificates, but an app's
  script would be same-site with ICS. Rejected; GitHub and Google keep user
  content on separate domains for the same reason.
- **HTML bundles with a key-value store.** No schema, no row scopes and no
  server-side rules; every check would live in code the user can change.
  Rejected.
- **Letting ICS roles imply app roles.** Easier to explain, but an editor of
  a document is not necessarily a reviewer of requests, and an owner should
  not silently see everyone's records. Rejected.

## Consequences

- An operator who wants apps runs the `compose.microapps.yaml` overlay, a
  second domain with a wildcard certificate, the `ics_apps` database and
  its backups ([Deploying ICS](../DEPLOY.md#micro-applications-optional)).
  Without the overlay nothing of this runs and the API answers
  `microapps_disabled`.
- App sources are visible only to publishers; search, relations, outlines and
  the security scan skip them.
- Destructive schema changes need a later contract version.
- The local profile (`scripts/microapps-local.sh`) runs the whole stack with
  an acceptance run through MCP and a real browser
  ([local profile](../development/microapps-local.md)).

## References

- [Micro-applications in the user guide](../guide/micro-applications.md)
- [Micro-applications API](../microapps-api.md)
- [Why HTML bundles run on a separate origin](../guide/formats.md#why-bundles-run-on-a-separate-origin)
- [ADR-0019](0019-agent-context-pack.md): what agents read

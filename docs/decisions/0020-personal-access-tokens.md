# ADR-0020: Personal access tokens and enforced scopes

**Status:** Accepted, 2026-09-26. Implemented (phase 4 of the document graph work). Amended
2026-10-29: OAuth access tokens lose admin powers the same way.
**Decision owners:** Owner.
**Scope:** new table `personal_access_tokens`, `backend/app/auth.py` (bearer branch),
`backend/app/permissions.py` (no admin bypass for PAT requests), a scope dependency on
writing routes, the `/api/admin/*` routers, `backend/app/audit.py` (`transport`), the
"Access tokens" page in the account menu, an e-mail template in `backend/app/i18n`, and
the rate limiter configuration.

## Context

The agent context pack (ADR-0019) is first reached through `ics-mcp`: PS tells the agent to
call `ics_task_context`. Measurements may show that agents skip that call, in which case PS
itself should embed the documents in the `task_start` response (the `IcsLive` client in
PS, modelled on how PS already reads OpenProject with an API key from `.env`).

PS runs locally as the developer who started it. It needs to call ICS as that person,
read only, without a browser. Today ICS authenticates with a session cookie (UI) or an OAuth
access token issued to `ics-mcp` (authorization code flow with rotating refresh tokens).
OAuth scopes are declared (`request.state.oauth_scopes`) but not enforced.

## Problem

1. How a local, non-interactive client authenticates as a person.
2. How to keep such a credential from becoming a stronger key than the person using it
   (admins in particular).
3. How to make a "read only" credential actually read only.

## Decision

### Options

| Option | Evaluation | Verdict |
|---|---|---|
| **A. Personal access token (PAT), read only** | PS acts as the person who runs it; ACL unchanged; same model as the OpenProject API key PS already uses | **chosen** |
| B. Service account (`client_credentials`) | access "above" users: a machine identity needs its own ACL model, and every PS user would see what the service account sees. PS acts for a person, so it does not fit | rejected |
| C. Share the `ics-mcp` OAuth token (read it from the keyring) | refresh tokens rotate on use: two processes refreshing one pair invalidate each other and log one of them out; it also couples PS to the internal storage format of another application | rejected |
| D. Mirror ICS metadata into the PS vault | stale data, permissions frozen at pull time, another sync mechanism | rejected |

### Token design

- Table `personal_access_tokens`: `id`, `user_id` (FK, `CASCADE`), `name`,
  `token_prefix` (8 characters, shown in the UI and logs to recognise a token),
  `token_hash`, `scopes`, `expires_at` (required), `last_used_at`, `revoked_at`,
  `created_at`. Index on `token_prefix`; partial index on `user_id WHERE revoked_at IS NULL`.
- Format `ics_pat_<prefix>_<secret>`, with 256 bits of randomness in the secret, shown once
  at creation.
- Stored as **SHA-256 with a server-side pepper** (a setting, not in the database). The
  secret is random and long, so a slow password hash adds nothing but latency on every
  request; the pepper makes a leaked table useless without the application secret.
  Comparison is constant time.
- **Expiry is required, at most 180 days.** No token lives forever.
- **At most 5 active tokens per user** (`pat_limit`).
- Scopes: `ics:read` now; `ics:write` is reserved and not issued until a use case needs it.

### Authentication

- The token arrives in the same `Authorization: Bearer` header as OAuth access tokens, so
  `app/auth.py` branches on the `ics_pat_` prefix **before** JWT verification.
- Every failure (unknown, revoked, expired, malformed) answers through `_bearer_401`, with
  `WWW-Authenticate`, the same contract as the OAuth bearer path. Clients rely on that
  header to tell an authentication problem from an application 401.
- The account lock (`locked_until`) applies as for the other transports. Locking an account
  revokes all its tokens; an admin can also revoke all tokens of a user.
- `request.state.oauth_transport = "pat"`, so the audit log and `context_pack_served`
  distinguish UI (`cookie`), MCP (`bearer`) and PS (`pat`).
- Rate limit as for MCP traffic (600 per minute), plus the per endpoint limits such as the
  120 per minute of `/api/context`.

### No admin bypass

`visible_assets_filter` and `effective_role` let a system admin see everything. A PAT of an
admin would therefore read the whole organisation from a file in a developer's `.env`. A
request authenticated with a PAT is evaluated **as an ordinary user**: the admin branches of
`effective_role`, `visible_assets_filter` and the graph access predicate (ADR-0016) are
skipped, and all `/api/admin/*` routes reject PAT requests with 403. An admin who needs
admin powers uses the browser.

Amended 2026-10-29: the same holds for OAuth access tokens. An MCP client connected by an
admin otherwise read every document and could call `/api/admin/*`, so a leaked token gave the
holder the whole organisation. MCP has no admin tools, so nothing it offers depends on it.

### Enforced scopes

`ics:read` blocks every method other than `GET` and `HEAD`, through a dependency on the
routers, not a check inside handlers. A parity test walks all routes and fails if a writing
route lacks the gate. The same mechanism later enforces OAuth scopes, which are declared
today but not checked. Error code `insufficient_scope` (403).

### UI and notifications

"Access tokens" in the account menu: list (name, prefix, scopes, expiry, last use), create,
revoke. Creating a token sends the owner an e-mail (text from `backend/app/i18n`, locale
through `resolve_locale`), so a token created by someone else with the session is noticed.
Audit actions `pat_created`, `pat_revoked`.

New error codes `pat_limit`, `pat_expiry_invalid`, `insufficient_scope`, added to
`docs/api-errors.md` and `frontend/src/lib/errorMessages.ts`.

Estimate (phase 4, ICS part): about 2.5 days backend, 1 day frontend.

## Reactivation trigger

- A write use case for PS (for example publishing a report as a deliverable without an
  agent): introduce `ics:write` with its own review.
- A machine integration that genuinely acts for no person (CI publishing to a shared
  project): revisit service accounts with a dedicated ACL.
- Evidence of token leakage or misuse: shorten the maximum lifetime or require IP binding.

## Consequences

- ICS gains a third authentication transport; the bearer branch must keep PAT and JWT paths
  separate and share the 401 contract.
- Admin tokens are deliberately weaker than admin sessions.
- The scope gate on all writing routes is new infrastructure that also closes the gap of
  unenforced OAuth scopes.
- Tokens expire within 180 days, so PS must report an expired token clearly (it gets a
  bearer 401 with `WWW-Authenticate`).

## References

- `backend/app/auth.py` (`_bearer_401`), `backend/app/permissions.py`,
  `backend/app/audit.py`.
- ADR-0016 (graph access), ADR-0019 (context pack).

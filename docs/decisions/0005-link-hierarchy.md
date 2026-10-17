# ADR-0005: Link hierarchy: `/v/<slug>` resolves to an access channel

**Status:** Accepted (2026-09-21).

## Context

ICS has two addresses leading to the same content, and until now they knew
nothing about each other:

- `/v/<slug>`: the internal address. Authorized through `effective_role`: the
  owner, a sys admin, a project member, an `AssetShare` recipient.
- `/s/<token>`: a capability address with four modes: `public`, `org_sso`,
  `password`, `magic_email`.

People copy what they have in the browser's address bar and paste it into the
team chat. So they paste `/v/<slug>`, and the recipient hits a wall: "Only the
document owner can open this URL. If someone shared it with you, ask them for
a `/s/...` link". Even someone with full access, who was only missing a
sign-in in that browser, got that wall.

## Problem

Three separate gaps that together produce one symptom:

1. `/v/` does not know share links exist, so it cannot send anyone anywhere.
2. The address bar never shows an address suitable for sharing, so copying
   from the browser is wrong by definition.
3. `/s/` does not know the person opening it is a team member. The Bearer
   path (MCP) already had this bypass, the browser path did not, so an owner
   being asked for the password to their own document was the normal state.

## Decision

Three orderings, kept apart on purpose, because confusing them was the trap.

### A. The asset's canonical address

Stable and independent of the visitor. Computed in
`services.link_resolution.pick_canonical`, returned in the `/doc` payload as
`canonical_url`, and the reader rewrites the address bar to it
(`replaceState`, only on `/v/`). The same choice is used by the notification
dispatcher (`services/notifications/_link_resolver.py`), which previously had
its own copy of the mode preferences and could advertise a different link
than the UI for the same asset.

1. an active `org_sso`
2. an active `public`
3. none → stays `/v/<slug>`

`password` and `magic_email` never qualify: the URL alone does not open them,
so advertising them as "the document's address" would promise access the link
does not give. On a tie the link without an expiry date wins, then the older
one, so a freshly created second link does not silently move an address people
have already shared.

`canonical_url` is returned only to roles that can share externally anyway
(`permissions.can_share_externally`: the file owner, the project owner). A
token grants anonymous read, and listing links is limited to the same roles,
so putting it in the payload for every editor and viewer would let them hand
out access they are not allowed to grant. A reader without that right stays on
`/v/<slug>`, and that is enough, because the resolver will open that address
for anyone they send it to.

### Links that must not be advertised

Shared by A and B (`_advertisable`): a link with `max_views` is not an address
but a one-time pass issued to a specific person. Pointing anyone else to it,
whether the owner opening the document from the panel or a random visitor with
a pasted `/v/`, would burn the budget that belongs to the recipient and leave
them with a 410.

### B. The entry resolver (`GET /api/assets/by-slug/{slug}/entry`)

Depends on the visitor. Order:

| # | Condition | Result |
|---|---|---|
| 1 | has a role on the asset | `view`: render `/v/` |
| 2 | signed in, domain on the whitelist, an `org_sso` exists | `redirect` to that link |
| 3 | a `public` exists | `redirect` |
| 4 | a `password` exists | `redirect` (password challenge on arrival) |
| 5 | signed in, address on the list, a `magic_email` exists | `redirect` |
| 6 | not signed in, an `org_sso` exists | `login`; after sign-in the resolver runs again |
| 7 | none of the above | 404 |

The resolver returns data, not frontend addresses: `redirect` carries a ready
share URL, `login` only the slug. The login route (`#login?next=`) is built by
the SPA router, because it owns that route.

An exception to the "least effort" rule: a user with a matching domain gets
the `org_sso` link before the public one, because that link identifies them
(audit log, and the view does not pretend they are a stranger).

Matching is per link, not per mode: two `magic_email` links on one asset point
at different recipients, so checking only the oldest one would turn away the
holder of the newer one.

Dead links (revoked, expired, budget exhausted) do not take part in the queue;
otherwise the redirect would land on a 410 instead of the content.

### C. `/s/<token>` opened by someone with a role

The mode gate is skipped (`_direct_role` in `routes/shares/_shared.py`), the
read does not consume `max_views`, and `share_info` returns `my_role` and
`slug`. The frontend mounts the full reader at that address instead of the
reduced guest view. **The address stays `/s/<token>`**: a hard redirect to
`/v/` would defeat point A, because the address bar would never show a link
suitable for sharing.

Link lifecycle gates (revoked, expired, exhausted → 410) apply to everyone,
with or without a role. There is a single definition,
`link_resolution.link_lifecycle`: `_resolve_share` maps the reason to its 410
message and the resolver simply filters out dead links, so a new gate cannot
end up on only one side. Likewise, the mode rule (`mode_admits`) is shared by
the resolver, the cookie path and the Bearer path. A revoked link must be dead
no matter who asks: the same semantics that `shares/resolve.py` has had since
the Bearer bypass.

## Options considered

**The address bar shows `/s/<token>` (chosen).** Copying from the browser
gives a link that works for the recipient. Cost: one asset has two addresses
in circulation.

**`/v/<slug>` as the only canonical address, with a smart resolver serving
the content.** Rejected: the slug would become a second public address, which
breaks the "a slug alone reveals nothing" principle more than necessary.

**"Request access" with a notification to the owner.** Deferred. Branch 7
stays at 404. To be done if it turns out to still be a common case.

## Consequences

### Security

The resolver chips at the principle "a non-owner gets a 404 so the existence
of the asset does not leak". Deliberately and narrowly:

- the resolver **does not serve content**, it only points to a channel;
- it confirms that the asset exists only when a channel exists that would open
  it anyway. Someone who knows the slug and gets a `redirect` to a public link
  learns the same thing they would by opening that link;
- "no way in" and "no such slug" are the same response, byte for byte;
- the endpoint is rate limited per IP (`ratelimit.LINK_ENTRY`, 30/min): it is
  the only asset endpoint that answers anonymous callers, and so the cheapest
  surface for slug enumeration;
- revealing a `password` link token to someone who knows the slug does not
  grant access: the password still applies, and the rate limit bucket is
  shared by both challenge paths.

`get_optional_user` collapses every 4xx into "anonymous", including 403 (a
locked account, a wrong domain). Such a caller is no better off than an
anonymous one anyway, and the resolver must not reveal why.

### Performance

The link mode gate runs before the role check: it admits most visitors and
costs nothing, while establishing identity is a Redis round trip plus up to
three SELECTs. Only the two endpoints that count a view (`/doc`,
`/html-grant`) compute the role. Identity is also cached on `request.state`,
because `share_static` is called once for every file of an HTML bundle.

`canonical_url` on `/doc` filters out non-qualifying links in SQL, not in
Python: it is the hottest read endpoint.

### Operational

- `/v/` links shared earlier start working without any action from owners.
- Views (`view_count`) stop growing from team reads, so historical counters
  are inflated compared with new ones. Nothing migrates them.
- The canonical address changes when the owner revokes the link it comes from.
  Previously shared copies stop working, as they always did after a revoke.
- Notifications stop linking to shares with a view limit. Previously the first
  person to click a notification burned a budget issued to someone else.

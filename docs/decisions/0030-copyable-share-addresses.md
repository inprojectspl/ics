# Copyable share addresses

Status: accepted

## Context

HTML bundles and micro-applications run on origins of their own and know
the visitor by a cookie of that origin (`ics_html_access`, the broker's app
session). A visitor who opened `/s/<token>` ends up on an address that no
longer names the link. The sender can reload it (the cookie is there); a
recipient of the copied address gets "open the document through ICS" or the
ICS sign-in, and loses the page and the section the sender meant.

## Problem

A copied address must take an independent recipient through the same share
link (its gate, limits and permissions) to the same page, query and
fragment, without changing domains, RBAC, sandboxing, storage or the
published packages, and without making the address a credential.

## Decision

Options considered:

| Option | Assessment |
|---|---|
| Add the token once, after the first open | Lost on the next navigation. |
| Pick another live link of the asset by slug | Not the sender's link: other gate, limits and permissions. |
| Fixed parent page with the asset in an iframe | Wider change, conflicts with the current CSP and cookies. |
| Shared script injected by the platform plus the existing link entry | **Chosen.** One place for every asset, packages untouched. |

- The address carries the link as `ics_share=<token>`, at most once, in the
  query. It names the link and grants nothing: the server checks it on every
  page load against the session (a live link of this asset; for a link
  visitor the very link of their session).
- ICS and the broker inject `share_context.js` (one source,
  `backend/app/static`) into every served HTML page, as an external classic
  script in the head. It keeps the token in links, History API calls and GET
  forms of the asset's own pages and remembers it per tab and asset in
  `sessionStorage`; it renders nothing and makes no requests.
- A page without a valid session gets an entry page with no asset content,
  whose script keeps the full address (the fragment never reaches a server)
  and goes through the link's existing entry (`/s/<token>?to=`,
  `/__ics/share?token=&to=`). The grant, the app launch and the share page
  carry the page back (`to`), checked to stay inside the asset.
- A member keeps their own access when opening a link; the address keeps the
  link anyway. An open from the panel is a one-shot *direct* entry that
  clears the tab's link context.
- One switch, `ICS_SHARE_CONTEXT_ENABLED`, covers ICS and the broker and
  stops the injection only.

Contract and limits: [Copyable asset addresses](../copyable-addresses.md).

## Consequences

- The share token is readable by the asset's own JavaScript and appears in
  the address bar and in proxy logs that keep query strings, as `/s/<token>`
  already does.
- Every HTML page is buffered to inject the script (it already was for the
  version banners); subresources still stream.
- The head insertion and URL rules exist twice (Python for ICS, JavaScript
  for the broker) with mirrored tests.
- A new tab opened by app code with `window.open` keeps the link only through
  `window.icsShareContext.withContext()`.

## Reactivation trigger

Revisit if assets move to a shared parent page, if share links get
per-visit tokens, or if the injection has to cover non-HTML documents.

## References

- `backend/app/services/share_context.py`, `backend/app/static/share_context.js`
- `microapp-runtime/src/broker/share-context.js`
- `local/microapps/acceptance/share_context.py`
